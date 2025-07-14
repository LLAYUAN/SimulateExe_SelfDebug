#!/usr/bin/env python3
"""
串行处理 humanevalpack.jsonl 数据集中的 buggy 代码
对每个代码进行自动调试修复，并测试修复后代码的正确率
"""

import json
import os
import time
import signal
from typing import Dict, List, Tuple, Optional
import traceback

from complete_cfg_builder import TextCFG
from utils import run_check_function, write_str_to_file
from chat import chat_selfdebug

# 全局标志用于优雅停止
shutdown_event = False

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

def process_single_task(task_data: dict, task_index: int, timeout: int = 300) -> Tuple[str, bool, Optional[bool], str, str]:
    """
    处理单个任务
    返回: (task_id, debug_success, test_passed, error_type, details)
    """
    global shutdown_event
    
    task_id = task_data.get('task_id', f'Unknown_{task_index}')
    
    # 检查是否需要停止
    if shutdown_event:
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
        
        print(f"[{task_index}] Processing {task_id} - {func_name}")
        
        # 创建临时代码文件
        temp_filename = f"temp_buggy_code_{task_index}.py"
        
        try:
            write_str_to_file(buggy_code, temp_filename)
            
            # 构建CFG
            cfg_start_time = time.time()
            try:
                textcfg = TextCFG(temp_filename, func_name)
                cfg_text = textcfg.cfg_text
                cfg_duration = time.time() - cfg_start_time
                print(f"[{task_index}] CFG built in {cfg_duration:.2f}s for {task_id}")
            except Exception as e:
                print(f"[{task_index}] CFG construction failed for {task_id}: {str(e)[:100]}...")
                return task_id, False, None, "cfg_error", f"CFG error: {str(e)}"
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass  # 忽略删除错误
        
        # 检查是否需要停止或超时
        if shutdown_event:
            return task_id, False, None, "shutdown", "Process was shut down"
        
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 60:  # 留60秒缓冲
            print(f"[{task_index}] Task {task_id} approaching timeout ({elapsed_time:.1f}s), skipping")
            return task_id, False, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
        
        # 调用selfdebug函数
        debug_result = None
        max_retries = 2  # 最多重试2次
        
        for attempt in range(max_retries):
            try:
                # 检查剩余时间
                elapsed_time = time.time() - task_start_time
                if elapsed_time > timeout - 90:  # 留90秒缓冲给测试
                    print(f"[{task_index}] Task {task_id} approaching timeout, skipping debug")
                    return task_id, False, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
                
                print(f"[{task_index}] Starting debug for {task_id} (attempt {attempt + 1})")
                debug_start_time = time.time()
                
                debug_result = chat_selfdebug(buggy_code, example_test, task_description, cfg_text)
                
                debug_duration = time.time() - debug_start_time
                print(f"[{task_index}] Debug completed in {debug_duration:.2f}s for {task_id}")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                debug_duration = time.time() - debug_start_time
                print(f"[{task_index}] Debug attempt {attempt + 1} failed for {task_id} after {debug_duration:.2f}s: {str(e)[:100]}...")
                
                if attempt == max_retries - 1:  # 最后一次尝试
                    return task_id, False, None, "debug_error", f"Debug error: {str(e)}"
                else:
                    time.sleep(2)  # 重试等待时间
        
        # 解析调试结果
        try:
            result_json = json.loads(debug_result)
            if 'corrected_code' not in result_json or not result_json['corrected_code']:
                print(f"[{task_index}] No corrected code returned for {task_id}")
                return task_id, False, None, "debug_error", "No corrected code in result"
            
            corrected_code = result_json['corrected_code']
            
        except json.JSONDecodeError as e:
            print(f"[{task_index}] Failed to parse debug result for {task_id}: {str(e)[:100]}...")
            return task_id, False, None, "debug_error", f"JSON parse error: {str(e)}"
        
        # 检查是否需要停止或超时
        if shutdown_event:
            return task_id, False, None, "shutdown", "Process was shut down"
        
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 30:  # 留30秒缓冲
            print(f"[{task_index}] Task {task_id} timeout before testing ({elapsed_time:.1f}s)")
            return task_id, True, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s"
        
        # 测试修正后的代码
        try:
            test_start_time = time.time()
            test_passed = run_check_function(func_name, test_code, corrected_code)
            test_duration = time.time() - test_start_time
            
            total_duration = time.time() - task_start_time
            
            if test_passed:
                print(f"[{task_index}] ✅ SUCCESS: {task_id} - Fixed and tests passed! (Total: {total_duration:.2f}s)")
                return task_id, True, True, None, "Success"
            else:
                print(f"[{task_index}] ❌ FAIL: {task_id} - Fixed but tests failed (Total: {total_duration:.2f}s)")
                return task_id, True, False, None, "Tests failed"
                
        except Exception as e:
            print(f"[{task_index}] Test execution failed for {task_id}: {str(e)[:100]}...")
            return task_id, True, None, "test_error", f"Test execution error: {str(e)}"
    
    except Exception as e:
        total_duration = time.time() - task_start_time
        print(f"[{task_index}] Unexpected error processing {task_id} after {total_duration:.2f}s: {str(e)[:100]}...")
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
                        print(f"Error parsing line {line_num}: {e}")
        return tasks
    except FileNotFoundError:
        print(f"Dataset file {file_path} not found!")
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
        print(f"Detailed results saved to {output_file}")
    except Exception as e:
        print(f"Failed to save results: {e}")

def signal_handler(signum, frame):
    """信号处理器，用于优雅停止"""
    global shutdown_event
    print("Received interrupt signal. Shutting down gracefully...")
    shutdown_event = True

def main():
    """主函数"""
    global shutdown_event
    
    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    dataset_file = "data/humanevalfix/humanevalpack.jsonl"
    task_timeout = 600  # 每个任务5分钟超时
    task_limit = None  # 限制处理任务数，None表示处理全部
    
    print("Starting serial debugging of HumanEval dataset...")
    print(f"Loading dataset from {dataset_file}")
    print(f"Task timeout: {task_timeout}s")
    if task_limit:
        print(f"Task limit: {task_limit} (for testing)")
    else:
        print("Processing full dataset")
    
    # 加载数据集
    tasks = load_dataset(dataset_file, task_limit)
    if not tasks:
        print("No tasks loaded. Exiting.")
        return
    
    print(f"Loaded {len(tasks)} tasks")
    
    # 初始化结果收集器
    results = DebugResults()
    
    # 开始时间记录
    start_time = time.time()
    
    # 串行处理每个任务
    try:
        for i, task_data in enumerate(tasks):
            if shutdown_event:
                print("Shutdown event detected, stopping...")
                break
            
            # 处理单个任务
            task_id, debug_success, test_passed, error_type, details = process_single_task(task_data, i, task_timeout)
            results.add_result(task_id, debug_success, test_passed, error_type, details)
            
            # 进度报告
            if (i + 1) % 10 == 0 or (i + 1) == len(tasks):
                elapsed = time.time() - start_time
                progress = (i + 1) / len(tasks) * 100
                rate = (i + 1) / elapsed * 60  # 每分钟处理数
                remaining_time = (len(tasks) - i - 1) / ((i + 1) / elapsed)
                
                print(f"\nProgress: {i + 1}/{len(tasks)} ({progress:.1f}%) "
                      f"- Elapsed: {elapsed:.1f}s ({rate:.1f}/min) "
                      f"- ETA: {remaining_time:.0f}s "
                      f"- Success: {results.test_passed}/{results.total_processed} "
                      f"- Errors: {results.debug_errors + results.cfg_errors + results.timeout_errors}")
            
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt. Stopping...")
        shutdown_event = True
    except Exception as e:
        print(f"Unexpected error in main loop: {str(e)}")
        shutdown_event = True
    
    # 计算总耗时
    total_time = time.time() - start_time
    
    # 打印最终结果
    results.print_summary()
    print(f"Total processing time: {total_time:.2f} seconds")
    if results.total_processed > 0:
        print(f"Average time per task: {total_time/results.total_processed:.2f} seconds")
        print(f"Processing rate: {results.total_processed/total_time*60:.1f} tasks/minute")
    
    # 保存详细结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = f"./dataset_test/humanevalfix/results/serial_debug_results_{timestamp}.json"
    save_detailed_results(results, output_file)

if __name__ == "__main__":
    main() 