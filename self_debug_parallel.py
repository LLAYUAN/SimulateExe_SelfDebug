#!/usr/bin/env python3
"""
批量处理 humanevalpack.jsonl 数据集中的 buggy 代码
对每个代码进行自动调试修复，并测试修复后代码的正确率
"""

import json
import os
import time
import signal
from typing import Dict, List, Tuple, Optional
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import threading

from complete_cfg_builder import TextCFG
from utils import extract_buggy_code, run_check_function, write_str_to_file
from chat import chat_selfdebug

# 线程锁用于保证输出和文件写入的线程安全
print_lock = threading.Lock()
results_lock = threading.Lock()

# 全局标志用于优雅停止
shutdown_event = threading.Event()

class DebugResults:
    """存储调试结果的类"""
    def __init__(self):
        self.total_processed = 0
        self.successful_fixes = 0
        self.test_passed = 0
        self.test_failed = 0
        self.debug_errors = 0
        self.cfg_errors = 0
        self.timeout_errors = 0
        self.results_details = []

    def add_result(self, task_id: str, success: bool, test_passed: Optional[bool], 
                   error_type: str = None, details: str = ""):
        """添加一个结果记录"""
        with results_lock:
            self.total_processed += 1
            if success:
                self.successful_fixes += 1
            if test_passed is True:
                self.test_passed += 1
            elif test_passed is False:  # 明确失败，而不是None
                self.test_failed += 1
            if error_type == "debug_error":
                self.debug_errors += 1
            elif error_type == "cfg_error":
                self.cfg_errors += 1
            elif error_type == "timeout_error":
                self.timeout_errors += 1
            
            self.results_details.append({
                'task_id': task_id,
                'success': success,
                'test_passed': test_passed,
                'error_type': error_type,
                'details': details
            })

    def print_summary(self):
        """打印统计摘要"""
        with print_lock:
            print("\n" + "="*60)
            print("FINAL RESULTS SUMMARY")
            print("="*60)
            print(f"Total processed: {self.total_processed}")
            print(f"Successful debug attempts: {self.successful_fixes}")
            print(f"Tests passed: {self.test_passed}")
            print(f"Tests failed: {self.test_failed}")
            print(f"Debug errors: {self.debug_errors}")
            print(f"CFG errors: {self.cfg_errors}")
            print(f"Timeout errors: {self.timeout_errors}")
            if self.total_processed > 0:
                print(f"Success rate: {self.successful_fixes/self.total_processed*100:.2f}%")
                print(f"Test pass rate: {self.test_passed/self.total_processed*100:.2f}%")
            print("="*60)

def safe_print(message: str):
    """线程安全的打印函数"""
    with print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {message}")

def process_single_task(task_data: dict, task_index: int, timeout: int = 180) -> Tuple[str, bool, Optional[bool], str, str]:
    """
    处理单个任务 - 减少超时时间到3分钟
    返回: (task_id, debug_success, test_passed, error_type, details)
    """
    task_id = task_data.get('task_id', f'Unknown_{task_index}')
    
    # 检查是否需要停止
    if shutdown_event.is_set():
        return task_id, False, None, "shutdown", "Process was shut down"
    
    # 任务开始时间
    task_start_time = time.time()
    
    try:
        # 提取基本信息
        func_name = task_data['entry_point']
        buggy_code = task_data['declaration'] + task_data['buggy_solution']
        example_test = task_data['example_test']
        test_code = task_data['test']
        task_description = task_data['docstring']
        
        safe_print(f"[{task_index}] Processing {task_id} - {func_name}")
        
        # 创建临时代码文件 - 使用线程ID确保唯一性
        thread_id = threading.get_ident()
        temp_filename = f"temp_buggy_code_{task_index}_{thread_id}.py"
        
        try:
            write_str_to_file(buggy_code, temp_filename)
            
            # 构建CFG - 添加超时保护
            cfg_start_time = time.time()
            try:
                textcfg = TextCFG(temp_filename, func_name)
                cfg_text = textcfg.cfg_text
                cfg_duration = time.time() - cfg_start_time
                safe_print(f"[{task_index}] CFG built in {cfg_duration:.2f}s for {task_id}")
            except Exception as e:
                safe_print(f"[{task_index}] CFG construction failed for {task_id}: {str(e)[:100]}...")
                return task_id, False, None, "cfg_error", f"CFG error: {str(e)}"
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass  # 忽略删除错误
        
        # 检查是否需要停止或超时
        if shutdown_event.is_set():
            return task_id, False, None, "shutdown", "Process was shut down"
        
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 30:  # 留30秒缓冲
            safe_print(f"[{task_index}] Task {task_id} approaching timeout ({elapsed_time:.1f}s), skipping")
            return task_id, False, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
        
        # 调用selfdebug函数 - 减少重试次数
        debug_result = None
        max_retries = 1  # 只重试一次
        
        # 添加错峰延迟
        if task_index > 0:
            delay = min((task_index % 5) + 1, 3)  # 1-3秒错峰延迟
            time.sleep(delay)
        
        for attempt in range(max_retries):
            try:
                # 检查剩余时间
                elapsed_time = time.time() - task_start_time
                if elapsed_time > timeout - 60:  # 留60秒缓冲给测试
                    safe_print(f"[{task_index}] Task {task_id} approaching timeout, skipping debug")
                    return task_id, False, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
                
                safe_print(f"[{task_index}] Starting debug for {task_id} (attempt {attempt + 1})")
                debug_start_time = time.time()
                
                debug_result = chat_selfdebug(buggy_code, example_test, task_description, cfg_text)
                
                debug_duration = time.time() - debug_start_time
                safe_print(f"[{task_index}] Debug completed in {debug_duration:.2f}s for {task_id}")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                debug_duration = time.time() - debug_start_time
                safe_print(f"[{task_index}] Debug attempt {attempt + 1} failed for {task_id} after {debug_duration:.2f}s: {str(e)[:100]}...")
                
                if attempt == max_retries - 1:  # 最后一次尝试
                    return task_id, False, None, "debug_error", f"Debug error: {str(e)}"
                else:
                    time.sleep(3)  # 重试等待时间
        
        # 解析调试结果
        try:
            result_json = json.loads(debug_result)
            if 'corrected_code' not in result_json or not result_json['corrected_code']:
                safe_print(f"[{task_index}] No corrected code returned for {task_id}")
                return task_id, False, None, "debug_error", "No corrected code in result"
            
            corrected_code = result_json['corrected_code']
            
        except json.JSONDecodeError as e:
            safe_print(f"[{task_index}] Failed to parse debug result for {task_id}: {str(e)[:100]}...")
            return task_id, False, None, "debug_error", f"JSON parse error: {str(e)}"
        
        # 检查是否需要停止或超时
        if shutdown_event.is_set():
            return task_id, False, None, "shutdown", "Process was shut down"
        
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 10:  # 留10秒缓冲
            safe_print(f"[{task_index}] Task {task_id} timeout before testing ({elapsed_time:.1f}s)")
            return task_id, True, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
        
        # 测试修正后的代码
        try:
            test_start_time = time.time()
            test_passed = run_check_function(func_name, test_code, corrected_code)
            test_duration = time.time() - test_start_time
            
            total_duration = time.time() - task_start_time
            
            if test_passed:
                safe_print(f"[{task_index}] ✅ SUCCESS: {task_id} - Fixed and tests passed! (Total: {total_duration:.2f}s)")
                return task_id, True, True, None, "Success"
            else:
                safe_print(f"[{task_index}] ❌ FAIL: {task_id} - Fixed but tests failed (Total: {total_duration:.2f}s)")
                return task_id, True, False, None, "Tests failed"
                
        except Exception as e:
            safe_print(f"[{task_index}] Test execution failed for {task_id}: {str(e)[:100]}...")
            return task_id, True, None, "test_error", f"Test execution error: {str(e)}"
    
    except Exception as e:
        total_duration = time.time() - task_start_time
        safe_print(f"[{task_index}] Unexpected error processing {task_id} after {total_duration:.2f}s: {str(e)[:100]}...")
        return task_id, False, None, "unexpected_error", f"Unexpected error: {str(e)}"

def load_dataset(file_path: str, limit: Optional[int] = None) -> List[dict]:
    """加载数据集"""
    tasks = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if limit and len(tasks) >= limit:
                    break
                line = line.strip()
                if line:
                    try:
                        task_data = json.loads(line)
                        tasks.append(task_data)
                    except json.JSONDecodeError as e:
                        safe_print(f"Error parsing line {line_num}: {e}")
        return tasks
    except FileNotFoundError:
        safe_print(f"Dataset file {file_path} not found!")
        return []

def save_detailed_results(results: DebugResults, output_file: str):
    """保存详细结果到文件"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'summary': {
                    'total_processed': results.total_processed,
                    'successful_fixes': results.successful_fixes,
                    'test_passed': results.test_passed,
                    'test_failed': results.test_failed,
                    'debug_errors': results.debug_errors,
                    'cfg_errors': results.cfg_errors,
                    'timeout_errors': results.timeout_errors,
                    'success_rate': results.successful_fixes/results.total_processed if results.total_processed > 0 else 0,
                    'test_pass_rate': results.test_passed/results.total_processed if results.total_processed > 0 else 0
                },
                'details': results.results_details
            }, f, indent=2, ensure_ascii=False)
        safe_print(f"Detailed results saved to {output_file}")
    except Exception as e:
        safe_print(f"Failed to save results: {e}")

def signal_handler(signum, frame):
    """信号处理器，用于优雅停止"""
    safe_print("Received interrupt signal. Shutting down gracefully...")
    shutdown_event.set()

def main():
    """主函数"""
    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    dataset_file = "data/humanevalfix/humanevalpack.jsonl"
    max_workers = 8  # 进一步减少并发数
    task_timeout = 180  # 每个任务3分钟超时
    overall_timeout = 1800  # 总体30分钟超时
    task_limit = None  # 限制处理任务数，避免hang住太久
    
    safe_print("Starting batch debugging of HumanEval dataset...")
    safe_print(f"Loading dataset from {dataset_file}")
    safe_print(f"Max workers: {max_workers}, Task timeout: {task_timeout}s, Overall timeout: {overall_timeout}s")
    if task_limit:
        safe_print(f"Task limit: {task_limit} (for testing)")
    else:
        safe_print("Processing full dataset")
    
    # 加载数据集
    tasks = load_dataset(dataset_file, task_limit)
    if not tasks:
        safe_print("No tasks loaded. Exiting.")
        return
    
    safe_print(f"Loaded {len(tasks)} tasks")
    
    # 初始化结果收集器
    results = DebugResults()
    
    # 开始时间记录
    start_time = time.time()
    
    # 使用线程池并行处理
    completed_futures = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_index = {}
            for i, task_data in enumerate(tasks):
                if shutdown_event.is_set():
                    break
                future = executor.submit(process_single_task, task_data, i, task_timeout)
                future_to_index[future] = i
            
            safe_print(f"Submitted {len(future_to_index)} tasks to executor")
            
            # 处理完成的任务 - 改进超时控制
            try:
                for future in as_completed(future_to_index, timeout=overall_timeout):
                    if shutdown_event.is_set():
                        safe_print("Shutdown event detected, stopping...")
                        break
                    
                    task_index = future_to_index[future]
                    try:
                        # 获取任务结果，设置合理的超时时间
                        task_id, debug_success, test_passed, error_type, details = future.result(timeout=task_timeout + 30)
                        results.add_result(task_id, debug_success, test_passed, error_type, details)
                        completed_futures.append(future)
                    
                        # 更频繁的进度报告
                        if results.total_processed % 5 == 0 or results.total_processed == len(tasks):
                            elapsed = time.time() - start_time
                            progress = results.total_processed / len(tasks) * 100
                            rate = results.total_processed / elapsed * 60  # 每分钟处理数
                            safe_print(f"Progress: {results.total_processed}/{len(tasks)} ({progress:.1f}%) "
                                         f"- Elapsed: {elapsed:.1f}s ({rate:.1f}/min) "
                                         f"- Success: {results.test_passed}/{results.total_processed} "
                                         f"- Errors: {results.debug_errors + results.cfg_errors + results.timeout_errors}")
                        
                    except TimeoutError:
                        safe_print(f"Task {task_index} result timeout after {task_timeout + 30}s")
                        results.add_result(f"task_{task_index}", False, None, "timeout_error", 
                                         f"Task result timeout after {task_timeout + 30}s")
                        completed_futures.append(future)
                    except Exception as e:
                        safe_print(f"Task {task_index} generated an exception: {str(e)[:100]}...")
                        results.add_result(f"task_{task_index}", False, None, "exception", str(e))
                        completed_futures.append(future)
                        
                    # 检查总体超时
                    if time.time() - start_time > overall_timeout:
                        safe_print(f"Overall timeout ({overall_timeout}s) reached, stopping...")
                        break
                        
            except TimeoutError:
                safe_print(f"Overall timeout ({overall_timeout}s) reached for as_completed")
                executor.shutdown(wait=False)
    
    except KeyboardInterrupt:
        safe_print("Received keyboard interrupt. Stopping...")
        shutdown_event.set()
        if 'executor' in locals():
            executor.shutdown(wait=False)
    except Exception as e:
        safe_print(f"Executor error: {str(e)[:100]}...")
        shutdown_event.set()
        if 'executor' in locals():
            executor.shutdown(wait=False)
    
    # 等待一小段时间让正在运行的任务完成
    if not shutdown_event.is_set():
        safe_print("Waiting for remaining tasks to complete...")
        time.sleep(5)
    
    # 检查是否有未完成的任务
    submitted_count = len(future_to_index) if 'future_to_index' in locals() else 0
    completed_count = len(completed_futures)
    processed_count = results.total_processed
    
    safe_print(f"Task summary: Submitted={submitted_count}, Completed={completed_count}, Processed={processed_count}")
    
    if submitted_count > completed_count:
        unfinished_count = submitted_count - completed_count
        safe_print(f"Warning: {unfinished_count} tasks may still be running")
    
    # 计算总耗时
    total_time = time.time() - start_time
    
    # 打印最终结果
    results.print_summary()
    safe_print(f"Total processing time: {total_time:.2f} seconds")
    if results.total_processed > 0:
        safe_print(f"Average time per task: {total_time/results.total_processed:.2f} seconds")
        safe_print(f"Processing rate: {results.total_processed/total_time*60:.1f} tasks/minute")
    
    # 保存详细结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = f"./dataset_test/humanevalfix/results/parallel_debug_results_{timestamp}.json"
    save_detailed_results(results, output_file)

if __name__ == "__main__":
    main() 