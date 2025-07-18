#!/usr/bin/env python3
"""
使用多轮调试方法并行处理 humanevalpack.jsonl 数据集
结合 self_debug_multi.py 的调试逻辑和并行处理框架
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
from chat import chat_selfdebug, chat_merge_debug_results
from loguru import logger

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
        self.no_test_cases = 0
        self.with_test_cases = 0
        self.results_details = []

    def add_result(self, task_id: str, success: bool, test_passed: Optional[bool], 
                   error_type: str = None, details: str = "", has_test_cases: bool = False):
        """添加一个结果记录"""
        with results_lock:
            self.total_processed += 1
            if success:
                self.successful_fixes += 1
            if test_passed is True:
                self.test_passed += 1
            elif test_passed is False:
                self.test_failed += 1
            if error_type == "debug_error":
                self.debug_errors += 1
            elif error_type == "cfg_error":
                self.cfg_errors += 1
            elif error_type == "timeout_error":
                self.timeout_errors += 1
            
            if has_test_cases:
                self.with_test_cases += 1
            else:
                self.no_test_cases += 1
            
            self.results_details.append({
                'task_id': task_id,
                'success': success,
                'test_passed': test_passed,
                'error_type': error_type,
                'details': details,
                'has_test_cases': has_test_cases
            })

    def print_summary(self):
        """打印统计摘要"""
        with print_lock:
            print("\n" + "="*60)
            print("MULTI-ROUND DEBUG RESULTS SUMMARY")
            print("="*60)
            print(f"Total processed: {self.total_processed}")
            print(f"Tasks with test cases: {self.with_test_cases}")
            print(f"Tasks without test cases: {self.no_test_cases}")
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

def extract_test_cases_from_example(example_test: str, func_name: str) -> List[str]:
    """
    从example_test中提取测试用例
    Args:
        example_test: 示例测试代码
        func_name: 函数名
    Returns:
        单个测试用例的列表
    """
    individual_tests = []
    
    # 分析example_test的结构
    lines = example_test.strip().split('\n')
    
    # 查找assert语句
    for line in lines:
        line = line.strip()
        if line.startswith('assert'):
            # 创建独立的测试函数
            test_func = f"""
def test_{func_name}():
    {line}

test_{func_name}()
"""
            individual_tests.append(test_func)
    
    return individual_tests

def process_single_task_multi(task_data: dict, task_index: int, timeout: int = 300) -> Tuple[str, bool, Optional[bool], str, str, bool]:
    """
    使用多轮调试方法处理单个任务
    返回: (task_id, debug_success, test_passed, error_type, details, has_test_cases)
    """
    task_id = task_data.get('task_id', f'task_{task_index}')
    
    # 检查是否需要停止
    if shutdown_event.is_set():
        return task_id, False, None, "shutdown", "Process was shut down", False
    
    # 任务开始时间
    task_start_time = time.time()
    
    try:
        # 提取基本信息
        func_name = task_data['entry_point']
        buggy_code = extract_buggy_code(task_data)
        example_test = task_data.get('example_test', '')
        test_code = task_data['test']
        task_description = task_data['docstring']
        
        safe_print(f"[{task_index}] Processing {task_id} - {func_name}")
        
        # 创建临时代码文件
        thread_id = threading.get_ident()
        temp_filename = f"temp_buggy_code_{task_index}_{thread_id}.py"
        
        try:
            write_str_to_file(buggy_code, temp_filename)
            
            # 构建CFG
            cfg_start_time = time.time()
            try:
                textcfg = TextCFG(temp_filename, func_name)
                cfg_text = textcfg.cfg_text
                cfg_duration = time.time() - cfg_start_time
                safe_print(f"[{task_index}] CFG built in {cfg_duration:.2f}s for {task_id}")
            except Exception as e:
                safe_print(f"[{task_index}] CFG construction failed for {task_id}: {str(e)[:100]}...")
                return task_id, False, None, "cfg_error", f"CFG error: {str(e)}", False
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass
        
        # 检查是否需要停止或超时
        if shutdown_event.is_set():
            return task_id, False, None, "shutdown", "Process was shut down", False
        
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 60:
            safe_print(f"[{task_index}] Task {task_id} approaching timeout ({elapsed_time:.1f}s), skipping")
            return task_id, False, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s", False
        
        # 提取测试用例
        test_cases = []
        has_test_cases = False
        
        if example_test:
            example_test_cases = extract_test_cases_from_example(example_test, func_name)
            test_cases.extend(example_test_cases)
            has_test_cases = len(test_cases) > 0
            safe_print(f"[{task_index}] Extracted {len(test_cases)} test cases for {task_id}")
        
        final_corrected_code = None
        
        if not test_cases:
            # 没有测试用例，直接使用合并调试功能
            safe_print(f"[{task_index}] No test cases found for {task_id}, using direct merge debug")
            
            basic_debug_result = {
                "test_case": "No test cases available",
                "bug_analysis": "No specific test cases to analyze, performing general code analysis",
                "corrected_code": buggy_code,
                "explanation": "No test cases provided, requiring general debugging approach"
            }
            
            individual_results = [json.dumps(basic_debug_result, ensure_ascii=False)]
            
            try:
                final_corrected_code = chat_merge_debug_results(
                    buggy_code=buggy_code,
                    individual_results=individual_results,
                    task_description=task_description
                )
                safe_print(f"[{task_index}] Direct merge debug completed for {task_id}")
            except Exception as e:
                safe_print(f"[{task_index}] Direct merge debug failed for {task_id}: {str(e)[:100]}...")
                return task_id, False, None, "debug_error", f"Direct debug error: {str(e)}", False
        
        else:
            # 有测试用例，进行多轮调试
            safe_print(f"[{task_index}] Starting multi-round debug for {task_id} with {len(test_cases)} test cases")
            
            # 第一阶段：为每个测试用例进行单独调试
            individual_results = []
            
            for i, test_case in enumerate(test_cases, 1):
                # 检查超时
                elapsed_time = time.time() - task_start_time
                if elapsed_time > timeout - 120:  # 留2分钟给合并
                    safe_print(f"[{task_index}] Timeout approaching during test case {i}/{len(test_cases)} for {task_id}")
                    break
                
                try:
                    safe_print(f"[{task_index}] Debugging test case {i}/{len(test_cases)} for {task_id}")
                    
                    full_debug_result = chat_selfdebug(
                        buggy_code=buggy_code,
                        example_test=test_case,
                        task_description=task_description,
                        text_cfg=cfg_text
                    )
                    
                    # 解析结果
                    try:
                        full_debug_json = json.loads(full_debug_result)
                        corrected_code = full_debug_json.get("corrected_code", buggy_code)
                        explanation = full_debug_json.get("explanation", "No explanation provided")
                        overall_analysis = full_debug_json.get("overall_analysis", {})
                        
                        simplified_result = {
                            "test_case": test_case.strip(),
                            "bug_analysis": overall_analysis.get("common_patterns", "Analysis from chat_selfdebug"),
                            "corrected_code": corrected_code,
                            "explanation": explanation
                        }
                        
                        individual_results.append(json.dumps(simplified_result, ensure_ascii=False))
                        safe_print(f"[{task_index}] Test case {i} debug completed for {task_id}")
                        
                    except json.JSONDecodeError as e:
                        safe_print(f"[{task_index}] JSON parse error for test case {i} of {task_id}: {str(e)[:100]}...")
                        simplified_result = {
                            "test_case": test_case.strip(),
                            "bug_analysis": "JSON parsing failed for chat_selfdebug result",
                            "corrected_code": buggy_code,
                            "explanation": f"Failed to parse chat_selfdebug result: {str(e)}"
                        }
                        individual_results.append(json.dumps(simplified_result, ensure_ascii=False))
                        
                except Exception as e:
                    safe_print(f"[{task_index}] Error debugging test case {i} of {task_id}: {str(e)[:100]}...")
                    error_result = {
                        "test_case": test_case,
                        "bug_analysis": f"调试过程中发生错误: {str(e)}",
                        "corrected_code": buggy_code,
                        "explanation": f"调试失败: {str(e)}"
                    }
                    individual_results.append(json.dumps(error_result, ensure_ascii=False))
            
            if not individual_results:
                safe_print(f"[{task_index}] No individual results for {task_id}")
                return task_id, False, None, "debug_error", "No individual debug results", has_test_cases
            
            # 第二阶段：合并所有结果
            try:
                safe_print(f"[{task_index}] Merging {len(individual_results)} debug results for {task_id}")
                final_corrected_code = chat_merge_debug_results(
                    buggy_code=buggy_code,
                    individual_results=individual_results,
                    task_description=task_description
                )
                safe_print(f"[{task_index}] Multi-round debug completed for {task_id}")
            except Exception as e:
                safe_print(f"[{task_index}] Merge debug failed for {task_id}: {str(e)[:100]}...")
                return task_id, False, None, "debug_error", f"Merge debug error: {str(e)}", has_test_cases
        
        # 检查是否获得了修正代码
        if not final_corrected_code or final_corrected_code == buggy_code:
            safe_print(f"[{task_index}] No corrected code generated for {task_id}")
            return task_id, False, None, "debug_error", "No corrected code generated", has_test_cases
        
        # 检查最终超时
        elapsed_time = time.time() - task_start_time
        if elapsed_time > timeout - 30:
            safe_print(f"[{task_index}] Task {task_id} timeout before testing ({elapsed_time:.1f}s)")
            return task_id, True, None, "timeout_error", f"Task timeout after {elapsed_time:.1f}s", has_test_cases
        
        # 测试修正后的代码
        try:
            test_start_time = time.time()
            test_passed = run_check_function(func_name, test_code, final_corrected_code)
            test_duration = time.time() - test_start_time
            
            total_duration = time.time() - task_start_time
            
            if test_passed:
                safe_print(f"[{task_index}] ✅ SUCCESS: {task_id} - Multi-round debug passed! (Total: {total_duration:.2f}s)")
                return task_id, True, True, None, "Success", has_test_cases
            else:
                safe_print(f"[{task_index}] ❌ FAIL: {task_id} - Fixed but tests failed (Total: {total_duration:.2f}s)")
                return task_id, True, False, None, "Tests failed", has_test_cases
                
        except Exception as e:
            safe_print(f"[{task_index}] Test execution failed for {task_id}: {str(e)[:100]}...")
            return task_id, True, None, "test_error", f"Test execution error: {str(e)}", has_test_cases
    
    except Exception as e:
        total_duration = time.time() - task_start_time
        safe_print(f"[{task_index}] Unexpected error processing {task_id} after {total_duration:.2f}s: {str(e)[:100]}...")
        return task_id, False, None, "unexpected_error", f"Unexpected error: {str(e)}", False

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
                    'with_test_cases': results.with_test_cases,
                    'no_test_cases': results.no_test_cases,
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
    
    dataset_file = "dataset_test/humanevalfix/humanevalpack.jsonl"
    max_workers = 8  # 适中的并发数，考虑到多轮调试的复杂性
    task_timeout = 300  # 每个任务5分钟超时（多轮调试需要更多时间）
    overall_timeout = 3600  # 总体60分钟超时
    task_limit = None  # 限制处理任务数，用于测试
    
    safe_print("Starting multi-round batch debugging of HumanEval dataset...")
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
                future = executor.submit(process_single_task_multi, task_data, i, task_timeout)
                future_to_index[future] = i
            
            safe_print(f"Submitted {len(future_to_index)} tasks to executor")
            
            # 处理完成的任务
            try:
                for future in as_completed(future_to_index, timeout=overall_timeout):
                    if shutdown_event.is_set():
                        safe_print("Shutdown event detected, stopping...")
                        break
                    
                    task_index = future_to_index[future]
                    try:
                        # 获取任务结果
                        task_id, debug_success, test_passed, error_type, details, has_test_cases = future.result(timeout=task_timeout + 60)
                        results.add_result(task_id, debug_success, test_passed, error_type, details, has_test_cases)
                        completed_futures.append(future)
                    
                        # 进度报告
                        if results.total_processed % 3 == 0 or results.total_processed == len(tasks):
                            elapsed = time.time() - start_time
                            progress = results.total_processed / len(tasks) * 100
                            rate = results.total_processed / elapsed * 60  # 每分钟处理数
                            safe_print(f"Progress: {results.total_processed}/{len(tasks)} ({progress:.1f}%) "
                                         f"- Elapsed: {elapsed:.1f}s ({rate:.1f}/min) "
                                         f"- Success: {results.test_passed}/{results.total_processed} "
                                         f"- With/Without tests: {results.with_test_cases}/{results.no_test_cases}")
                        
                    except TimeoutError:
                        safe_print(f"Task {task_index} result timeout after {task_timeout + 60}s")
                        results.add_result(f"task_{task_index}", False, None, "timeout_error", 
                                         f"Task result timeout after {task_timeout + 60}s", False)
                        completed_futures.append(future)
                    except Exception as e:
                        safe_print(f"Task {task_index} generated an exception: {str(e)[:100]}...")
                        results.add_result(f"task_{task_index}", False, None, "exception", str(e), False)
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
    
    # 等待剩余任务完成
    if not shutdown_event.is_set():
        safe_print("Waiting for remaining tasks to complete...")
        time.sleep(10)
    
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
    output_file = f"./dataset_test/humanevalfix/results/multi_debug_results_{timestamp}.json"
    save_detailed_results(results, output_file)
    
    safe_print(f"Multi-round debugging completed. Results saved to {output_file}")

if __name__ == "__main__":
    main() 