#!/usr/bin/env python3
"""
直接调用大模型修复代码的并行测试脚本
这个脚本测试仅使用大模型直接修复代码能达到的准确度，无需复杂的CFG分析
"""

import json
import os
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from loguru import logger
from pathlib import Path
from typing import Dict, Any, Tuple
from tqdm import tqdm
from chat import direct_fix_code
from utils import extract_buggy_code, run_check_function

def setup_logger_for_process(process_id: int):
    """为每个进程设置独立的日志文件"""
    log_file = f"direct_fix_log_process_{process_id}.txt"
    logger.add(log_file, encoding="utf-8", rotation="10 MB", retention="10 days")

def direct_fix_single_task(task_data: Tuple[int, str]) -> Tuple[int, bool, str]:
    """
    处理单个代码修复任务
    Args:
        task_data: (task_index, task_json_line)
    Returns:
        (task_index, is_success, error_message)
    """
    task_idx, line = task_data
    process_id = os.getpid()
    
    # 为当前进程设置日志
    setup_logger_for_process(process_id)
    
    try:
        logger.info(f"=================直接修复任务 {task_idx}=================")
        task = json.loads(line)
        function_name = task['entry_point']
        
        # 创建唯一的临时代码文件
        buggy_code_file = f"direct_buggy_proc_{process_id}_{task_idx}.py"
        
        # 提取错误代码
        buggy_code = extract_buggy_code(task, buggy_code_file)
        task_description = task['docstring']
        
        # 获取示例测试用例 - 使用第一个example test作为参考
        example_test = task['example_test']
        
        logger.info(f"函数名: {function_name}")
        logger.info(f"任务描述: {task_description}")
        logger.info(f"示例测试: {example_test}")
        
        # 直接调用大模型修复代码
        logger.info("开始调用大模型修复代码...")
        fixed_code = direct_fix_code(task_description, example_test, buggy_code)
        logger.info(f"修复后的代码:\n{fixed_code}")
        
        # 使用隐藏测试用例验证修复结果
        hidden_check_test = task['test']
        logger.info("开始验证修复结果...")
        is_success = run_check_function(function_name, hidden_check_test, fixed_code)
        
        # 清理临时文件
        try:
            if os.path.exists(buggy_code_file):
                os.remove(buggy_code_file)
        except Exception as e:
            logger.warning(f"清理临时文件失败 {buggy_code_file}: {e}")
        
        result_msg = "✅ 修复成功" if is_success else "❌ 修复失败"
        logger.info(f"任务 {task_idx} {result_msg}")
        
        return task_idx, is_success, ""
        
    except Exception as e:
        error_msg = f"任务 {task_idx} 处理异常: {str(e)}"
        logger.error(error_msg)
        
        # 清理临时文件
        try:
            buggy_code_file = f"direct_buggy_proc_{process_id}_{task_idx}.py"
            if os.path.exists(buggy_code_file):
                os.remove(buggy_code_file)
        except:
            pass
            
        return task_idx, False, error_msg

def direct_fix_all_tasks_parallel(dataset_path: str, max_workers: int = None):
    """
    并行处理所有代码修复任务
    Args:
        dataset_path: 数据集路径
        max_workers: 最大并行工作进程数，默认为CPU核心数
    """
    # 读取所有任务
    with open(dataset_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    total_tasks = len(lines)
    logger.info(f"总任务数: {total_tasks}")
    
    # 准备任务数据
    task_data_list = [(idx, line) for idx, line in enumerate(lines)]
    
    # 设置并行度
    if max_workers is None:
        max_workers = mp.cpu_count()
    
    logger.info(f"使用 {max_workers} 个并行进程")
    
    success_count = 0
    completed_count = 0
    results = {}
    error_details = {}
    
    # 使用进程池执行并行处理
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_task = {executor.submit(direct_fix_single_task, task_data): task_data[0] 
                         for task_data in task_data_list}
        
        # 使用tqdm显示进度
        progress_bar = tqdm(as_completed(future_to_task), total=total_tasks, desc="直接修复任务")
        
        for future in progress_bar:
            task_idx = future_to_task[future]
            try:
                task_idx_result, is_success, error_msg = future.result()
                results[task_idx_result] = is_success
                if error_msg:
                    error_details[task_idx_result] = error_msg
                    
                if is_success:
                    success_count += 1
                completed_count += 1
                
                # 更新进度条描述
                current_rate = success_count / completed_count
                progress_bar.set_description(f"直接修复任务 (成功率: {current_rate:.1%})")
                
                # 实时显示当前成功率
                if completed_count % 10 == 0 or completed_count == total_tasks:
                    print(f"\n当前进度: {success_count} / {completed_count} ({current_rate:.2%})")
                
            except Exception as e:
                logger.error(f"任务 {task_idx} 执行异常: {e}")
                results[task_idx] = False
                error_details[task_idx] = f"执行异常: {str(e)}"
                completed_count += 1

    # 最终统计
    final_success_rate = success_count / total_tasks
    print(f"\n{'='*50}")
    print(f"🎯 直接大模型修复 - 最终结果")
    print(f"{'='*50}")
    print(f"📊 总任务数: {total_tasks}")
    print(f"✅ 成功任务: {success_count}")
    print(f"❌ 失败任务: {total_tasks - success_count}")
    print(f"🎯 最终成功率: {final_success_rate:.2%}")
    print(f"{'='*50}")
    
    # 保存详细结果
    results_summary = {
        "experiment_type": "direct_llm_fix",
        "total_tasks": total_tasks,
        "success_count": success_count,
        "failure_count": total_tasks - success_count,
        "success_rate": final_success_rate,
        "detailed_results": results,
        "error_details": error_details,
        "max_workers": max_workers
    }
    
    results_file = "direct_fix_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)
    
    logger.info(f"详细结果已保存到 {results_file}")
    
    # 分析失败案例
    failed_tasks = [idx for idx, success in results.items() if not success]
    if failed_tasks:
        print(f"\n❌ 失败任务索引: {failed_tasks[:10]}{'...' if len(failed_tasks) > 10 else ''}")
        if error_details:
            print(f"📝 部分错误详情:")
            for idx, error in list(error_details.items())[:5]:
                print(f"  任务{idx}: {error}")
    
    return final_success_rate

if __name__ == "__main__":
    # 设置主进程日志
    logger.add("direct_fix_main.txt", encoding="utf-8", rotation="10 MB", retention="10 days")
    
    dataset_path = "./data/humanevalfix/humanevalpack.jsonl"
    
    # 检查数据集是否存在
    if not os.path.exists(dataset_path):
        print(f"❌ 数据集不存在: {dataset_path}")
        exit(1)
    
    print("🚀 直接大模型代码修复并行测试")
    print("=" * 50)
    max_workers = int(os.environ.get("MAX_WORKERS", mp.cpu_count()))
    logger.info(f"开始完整并行测试，使用 {max_workers} 个进程")
    final_rate = direct_fix_all_tasks_parallel(dataset_path, max_workers)
    print(f"\n🏁 实验完成！直接大模型修复成功率: {final_rate:.2%}") 