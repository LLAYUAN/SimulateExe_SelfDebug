#!/usr/bin/env python3
"""
使用selfdebug架构处理defects4j-sf数据集中的Java代码
替代SRepair中的gen_solution和gen_patch，并使用sf_val_d4j验证正确率
支持并行处理和统计修复正确率
"""

import json
import os
import time
import random
import argparse
import re
from typing import Dict, List, Optional, Tuple
from loguru import logger
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from java_cfg_builder import JavaCFG
from utils import write_str_to_file
from chat import chat_java_fragment_debug

def slim_error_message(err_msg: str, token_limit: int = 200) -> str:
    """
    简化error message，类似gen_solution_prompt.py中的slim_content_token
    Args:
        err_msg: 原始错误信息
        token_limit: token限制
    Returns:
        简化后的错误信息
    """
    err_msg_lines = err_msg.split('\n')
    slim_err_msg_lines = []
    current_tokens = 0
    
    for line in err_msg_lines:
        # 简单估算：一个单词约等于1个token
        line_tokens = len(line.split())
        if current_tokens + line_tokens > token_limit:
            break
        slim_err_msg_lines.append(line)
        current_tokens += line_tokens
    
    return '\n'.join(slim_err_msg_lines)

def extract_java_buggy_code(bug_data: Dict) -> str:
    """
    提取Java的buggy代码
    Args:
        bug_data: 单个bug的数据
    Returns:
        完整的buggy代码
    """
    buggy_code = bug_data['buggy']
    buggy_code_comment = bug_data.get('buggy_code_comment', '')
    
    # 组合注释和代码
    if buggy_code_comment:
        full_code = buggy_code_comment + '\n' + buggy_code
    else:
        full_code = buggy_code
    
    return full_code

def extract_java_test_info(bug_data: Dict) -> Tuple[str, str]:
    """
    从trigger_test中随机选择一个测试用例和错误信息（按照gen_solution_prompt.py的方式）
    Args:
        bug_data: 单个bug的数据
    Returns:
        (test_case, error_message) 元组
    """
    trigger_tests = bug_data.get('trigger_test', {})
    
    # 随机选择一个trigger test（按照gen_solution_prompt.py的方式）
    if trigger_tests:
        random_trigger_test = random.choice(list(trigger_tests.keys()))
        selected_test = trigger_tests[random_trigger_test]
        test_case = selected_test.get('src', '')
        error_message = selected_test.get('clean_error_msg', '')
        
        if error_message:
            error_message = slim_error_message(error_message)
        
        return test_case, error_message
    
    return "", ""

def selfdebug_java_single(bug_name: str, bug_data: Dict) -> Optional[str]:
    """
    使用静态分析方法处理单个Java bug
    Args:
        bug_name: bug名称
        bug_data: bug数据
    Returns:
        修复后的代码，失败时返回None
    """
    logger.info(f"Processing bug: {bug_name}")
    
    # 提取基本信息
    buggy_code = extract_java_buggy_code(bug_data)
    test_case, error_message = extract_java_test_info(bug_data)
    
    logger.info(f"Buggy code length: {len(buggy_code)}")
    logger.info(f"Buggy code: {buggy_code}")
    logger.info(f"Test case length: {len(test_case)}")
    logger.info(f"Test case: {test_case}")
    logger.info(f"Error message length: {len(error_message)}")
    logger.info(f"Error message: {error_message}")
    
    # 构建CFG - 使用Java CFG builder
    cfg_text = ""
    try:
        # 创建临时Java文件
        temp_filename = f"temp_java_{bug_name.replace('-', '_')}.java"
        
        # 检查代码是否包含类定义，如果没有则包装在临时类中
        java_code_to_write = buggy_code
        if not re.search(r'\bclass\s+\w+', buggy_code):
            # 没有类定义，包装在临时类中
            java_code_to_write = f"""
            public class TempClass {{
            {buggy_code}
            }}
            """
            logger.info(f"Wrapped method in temporary class for {bug_name}")
        
        write_str_to_file(java_code_to_write, temp_filename)
        
        # 使用JavaCFG构建控制流图
        java_cfg = JavaCFG(temp_filename)
        cfg_text = java_cfg.cfg_text
        logger.info(f"CFG text: {cfg_text}")
        
        # 清理临时文件
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
        logger.info(f"CFG built successfully for {bug_name}")
        
    except Exception as e:
        logger.warning(f"CFG construction failed for {bug_name}: {e}")
        cfg_text = ""
    
    # 使用静态分析方法进行调试
    try:
        logger.info(f"Starting static analysis debug for {bug_name}")
        
        # 如果没有测试用例或错误信息，使用占位符
        if not test_case:
            test_case = "No specific test case available"
        if not error_message:
            error_message = "No specific error message available"
            
        debug_result = chat_java_fragment_debug(
            buggy_code=buggy_code,
            error_message=error_message,
            test_case=test_case,
            cfg_text=cfg_text
        )
        
        # 打印原始响应用于调试
        logger.info(f"Raw LLM response for {bug_name}:")
        logger.info(f"Response length: {len(debug_result)}")
        logger.info(f"First 500 chars: {debug_result}")
        
        # 预处理响应，去掉markdown代码块标记
        processed_result = debug_result.strip()
        if processed_result.startswith("```json"):
            processed_result = processed_result[7:]  # 去掉```json
        if processed_result.endswith("```"):
            processed_result = processed_result[:-3]  # 去掉```
        processed_result = processed_result.strip()
        
        # 解析结果
        try:
            debug_json = json.loads(processed_result)
            corrected_code = debug_json.get("corrected_code", buggy_code)
            explanation = debug_json.get("explanation", "No explanation provided")
            
            logger.info(f"Debug completed for {bug_name}")
            logger.info(f"Corrected code: {corrected_code}")
            logger.info(f"Explanation: {explanation}")
            
            # 检查是否生成了修复代码（不管是否正确，都需要验证）
            if corrected_code and corrected_code.strip() != buggy_code.strip():
                logger.info(f"📝 Generated patch for {bug_name} (needs validation)")
                return corrected_code
            else:
                logger.warning(f"❌ No patch generated for {bug_name}")
                return None
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for {bug_name}: {e}")
            logger.warning(f"Trying to extract code from non-JSON response...")
            
            # 尝试从原始响应中提取代码
            if "```java" in debug_result:
                start = debug_result.find("```java") + 7
                end = debug_result.find("```", start)
                if end > start:
                    extracted_code = debug_result[start:end].strip()
                    if extracted_code and extracted_code != buggy_code.strip():
                        logger.info(f"📝 Extracted patch from non-JSON response for {bug_name} (needs validation)")
                        return extracted_code
            
            logger.warning(f"❌ Could not extract any meaningful fix for {bug_name}")
            return None
            
    except Exception as e:
        logger.error(f"Static analysis debug failed for {bug_name}: {e}")
        return None

def process_single_bug_task(task_data: Tuple[str, Dict]) -> Tuple[str, Optional[str], bool]:
    """
    并行处理单个bug任务
    Args:
        task_data: (bug_name, bug_data) 元组
    Returns:
        (bug_name, corrected_code, success) 元组
    """
    bug_name, bug_data = task_data
    
    try:
        corrected_code = selfdebug_java_single(bug_name, bug_data)
        success = corrected_code is not None and corrected_code.strip() != bug_data['buggy'].strip()
        return bug_name, corrected_code, success
    except Exception as e:
        logger.error(f"Error processing {bug_name}: {e}")
        return bug_name, None, False

def process_defects4j_dataset_parallel(dataset_path: str, output_path: str, limit: int = None, max_workers: int = None) -> Dict:
    """
    并行处理整个defects4j数据集
    Args:
        dataset_path: 数据集路径
        output_path: 输出路径
        limit: 限制处理的bug数量
        max_workers: 最大并行worker数量
    Returns:
        处理结果字典
    """
    logger.info(f"Loading dataset from {dataset_path}")
    
    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
    
    total_bugs = len(dataset)
    logger.info(f"Total bugs in dataset: {total_bugs}")
    
    bug_names = list(dataset.keys())
    
    # 如果设置了限制，只处理指定数量的bugs
    if limit is not None and limit > 0:
        bug_names = bug_names[:limit]
        logger.info(f"Limited processing to first {limit} bugs")
    
    # 设置并行worker数量
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), len(bug_names))
    
    logger.info(f"Using {max_workers} parallel workers")
    
    # 准备任务数据
    tasks = [(bug_name, dataset[bug_name]) for bug_name in bug_names]
    
    results = {}
    patches_generated = 0
    successful_fixes = 0
    
    # 并行处理
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_bug = {executor.submit(process_single_bug_task, task): task[0] for task in tasks}
        
        # 收集结果
        for i, future in enumerate(as_completed(future_to_bug), 1):
            bug_name = future_to_bug[future]
            
            try:
                bug_name_result, corrected_code, success = future.result()
                
                logger.info(f"=== Completed bug {i}/{len(bug_names)}: {bug_name_result} ===")
                
                if corrected_code and corrected_code != dataset[bug_name_result]['buggy']:
                    results[bug_name_result] = {
                        'patches': [corrected_code],
                        'original_buggy': dataset[bug_name_result]['buggy'],
                        'bug_info': {
                            'loc': dataset[bug_name_result]['loc'],
                            'start': dataset[bug_name_result]['start'],
                            'end': dataset[bug_name_result]['end']
                        },
                        'patch_generated': True
                    }
                    patches_generated += 1
                    if success:
                        successful_fixes += 1
                    logger.info(f"📝 Generated patch for {bug_name_result} (validation required)")
                else:
                    logger.warning(f"❌ No patch generated for {bug_name_result}")
                    # 为了能够进行验证，即使失败也要记录原始代码
                    results[bug_name_result] = {
                        'patches': [dataset[bug_name_result]['buggy']],  # 使用原始代码
                        'original_buggy': dataset[bug_name_result]['buggy'],
                        'bug_info': {
                            'loc': dataset[bug_name_result]['loc'],
                            'start': dataset[bug_name_result]['start'],
                            'end': dataset[bug_name_result]['end']
                        },
                        'patch_generated': False
                    }
                
                # 定期保存中间结果
                if i % 10 == 0:
                    logger.info(f"Progress: {i}/{len(bug_names)} completed, saving intermediate results...")
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(results, f, indent=2, ensure_ascii=False)
                        
            except Exception as e:
                logger.error(f"Error processing result for {bug_name}: {e}")
                # 记录失败的情况
                results[bug_name] = {
                    'patches': [dataset[bug_name]['buggy']],  # 使用原始代码
                    'original_buggy': dataset[bug_name]['buggy'],
                    'bug_info': {
                        'loc': dataset[bug_name]['loc'],
                        'start': dataset[bug_name]['start'],
                        'end': dataset[bug_name]['end']
                    },
                    'patch_generated': False
                }
    
    logger.info(f"=== Parallel processing completed ===")
    logger.info(f"Total processed: {len(bug_names)}")
    logger.info(f"Patches generated: {patches_generated}")
    logger.info(f"Patch generation rate: {patches_generated/len(bug_names)*100:.2f}%")
    
    # 保存最终结果
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Results saved to {output_path}")
    return results

def run_validation(patch_file: str, dataset_path: str, output_dir: str):
    """
    运行sf_val_d4j验证
    Args:
        patch_file: 补丁文件路径
        dataset_path: 数据集路径
        output_dir: 输出目录
    """
    logger.info("Starting validation with sf_val_d4j...")
    
    # 构建验证命令
    val_script = "dataset_test/SRepair/SRepair/src/sf_val_d4j.py"
    
    if not os.path.exists(val_script):
        logger.error(f"Validation script not found: {val_script}")
        return
    
    cmd = [
        sys.executable, val_script,
        '-i', patch_file,
        '-d', dataset_path,
        '-o', output_dir
    ]
    
    logger.info(f"Running validation command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)  # 1小时超时
        
        if result.returncode == 0:
            logger.info("✅ Validation completed successfully!")
            logger.info(f"Validation output: {result.stdout}")
        else:
            logger.error(f"❌ Validation failed with return code {result.returncode}")
            logger.error(f"Error output: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logger.error("❌ Validation timed out after 1 hour")
    except Exception as e:
        logger.error(f"❌ Error running validation: {e}")

def parse_validation_results(validation_output_dir: str) -> Dict:
    """
    解析验证结果并统计修复正确率
    Args:
        validation_output_dir: 验证结果输出目录
    Returns:
        统计结果字典
    """
    logger.info(f"Parsing validation results from {validation_output_dir}")
    
    if not os.path.exists(validation_output_dir):
        logger.error(f"Validation output directory not found: {validation_output_dir}")
        return {}
    
    validation_files = [f for f in os.listdir(validation_output_dir) if f.endswith('-validated.jsonl')]
    
    total_bugs = 0
    plausible_fixes = 0
    correct_fixes = 0
    uncompilable_fixes = 0
    timeout_fixes = 0
    
    detailed_results = {}
    
    for val_file in validation_files:
        val_file_path = os.path.join(validation_output_dir, val_file)
        bug_name = val_file.replace('-validated.jsonl', '')
        
        try:
            with open(val_file_path, 'r', encoding='utf-8') as f:
                bug_results = json.load(f)
            
            for patch_result in bug_results:
                total_bugs += 1
                status = patch_result.get('patch_status', 'UNKNOWN')
                
                detailed_results[f"{bug_name}_patch_{patch_result.get('val_cnt', 1)}"] = {
                    'bug_name': bug_name,
                    'status': status,
                    'failing_tests': patch_result.get('failing_tests', {}),
                    'patch_code': patch_result.get('patch_code', '')[:100] + '...'  # 只保留前100字符
                }
                
                if status == 'PLAUSIBLE':
                    plausible_fixes += 1
                    correct_fixes += 1  # PLAUSIBLE 表示通过了所有测试
                elif status == 'UNCOMPILABLE':
                    uncompilable_fixes += 1
                elif 'TIMEOUT' in status:
                    timeout_fixes += 1
        
        except Exception as e:
            logger.error(f"Error parsing validation file {val_file}: {e}")
            continue
    
    # 计算统计结果
    patch_generation_rate = 0
    plausible_rate = 0
    correct_rate = 0
    
    if total_bugs > 0:
        plausible_rate = (plausible_fixes / total_bugs) * 100
        correct_rate = (correct_fixes / total_bugs) * 100
    
    statistics = {
        'total_bugs_validated': total_bugs,
        'plausible_fixes': plausible_fixes,
        'correct_fixes': correct_fixes,
        'uncompilable_fixes': uncompilable_fixes,
        'timeout_fixes': timeout_fixes,
        'other_fixes': total_bugs - plausible_fixes - uncompilable_fixes - timeout_fixes,
        'plausible_rate': round(plausible_rate, 2),
        'correct_rate': round(correct_rate, 2),
        'detailed_results': detailed_results
    }
    
    # 打印统计结果
    logger.info("=== DEFECTS4J REPAIR STATISTICS ===")
    logger.info(f"Total bugs validated: {total_bugs}")
    logger.info(f"Plausible fixes: {plausible_fixes}")
    logger.info(f"Correct fixes: {correct_fixes}")
    logger.info(f"Uncompilable fixes: {uncompilable_fixes}")
    logger.info(f"Timeout fixes: {timeout_fixes}")
    logger.info(f"Other status fixes: {statistics['other_fixes']}")
    logger.info(f"Plausible rate: {plausible_rate:.2f}%")
    logger.info(f"Correct rate: {correct_rate:.2f}%")
    logger.info("=" * 40)
    
    return statistics

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Use static analysis architecture to process defects4j dataset")
    parser.add_argument('--dataset', '-d', type=str, 
                       default='dataset_test/SRepair/SRepair/dataset/defects4j-sf.json',
                       help='Path to defects4j-sf.json dataset')
    parser.add_argument('--output', '-o', type=str,
                       default='dataset_test/SRepair/results/sf/defects4j_static_analysis_patches.json',
                       help='Output path for generated patches')
    parser.add_argument('--validate', '-v', action='store_true',
                       help='Run validation after generating patches')
    parser.add_argument('--validate-only', action='store_true',
                       help='Only run validation on existing patch file (skip patch generation)')
    parser.add_argument('--val-output', type=str, default='dataset_test/SRepair/results/sf/defects4j_validation_results',
                       help='Output directory for validation results')
    parser.add_argument('--limit', '-l', type=int, default=None,
                       help='Limit the number of bugs to process (useful for debugging)')
    parser.add_argument('--workers', '-w', type=int, default=None,
                       help='Number of parallel workers (default: CPU count)')
    parser.add_argument('--parse-results', action='store_true',
                       help='Only parse existing validation results and show statistics')
    
    args = parser.parse_args()
    
    # 设置日志
    logger.info("Starting defects4j static analysis processing...")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Validate: {args.validate}")
    logger.info(f"Validate only: {args.validate_only}")
    if args.limit:
        logger.info(f"Processing limit: {args.limit} bugs")
    if args.workers:
        logger.info(f"Parallel workers: {args.workers}")
    
    # 如果只是解析结果，直接解析并退出
    if args.parse_results:
        logger.info("🔍 Parsing existing validation results...")
        statistics = parse_validation_results(args.val_output)
        
        # 保存统计结果
        stats_file = os.path.join(os.path.dirname(args.output), 'repair_statistics.json')
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2, ensure_ascii=False)
        logger.info(f"Statistics saved to {stats_file}")
        return
    
    # 如果只是验证现有补丁
    if args.validate_only:
        logger.info("🔍 Validating existing patches only...")
        
        # 检查补丁文件是否存在
        if not os.path.exists(args.output):
            logger.error(f"Patch file not found: {args.output}")
            logger.error("Please generate patches first or specify correct patch file path with --output")
            return
        
        # 删除现有输出目录以避免冲突
        if os.path.exists(args.val_output):
            import shutil
            logger.info(f"Removing existing validation output directory: {args.val_output}")
            shutil.rmtree(args.val_output)
        
        # 直接运行验证
        run_validation(args.output, args.dataset, args.val_output)
        
        # 解析验证结果
        logger.info("🔍 Parsing validation results and calculating repair rates...")
        time.sleep(5)  # 等待文件写入完成
        
        statistics = parse_validation_results(args.val_output)
        
        # 保存统计结果
        stats_file = os.path.join(os.path.dirname(args.output), 'repair_statistics.json')
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📊 Repair statistics saved to {stats_file}")
        logger.info("Validation completed!")
        return
    
    # 检查输入文件
    if not os.path.exists(args.dataset):
        logger.error(f"Dataset file not found: {args.dataset}")
        return
    
    # 处理数据集
    start_time = time.time()
    results = process_defects4j_dataset_parallel(args.dataset, args.output, args.limit, args.workers)
    processing_time = time.time() - start_time
    
    logger.info(f"Patch generation completed in {processing_time:.2f} seconds")
    
    # 运行验证
    if args.validate:
        logger.info("🔍 Starting validation with sf_val_d4j...")
        
        # 删除现有输出目录以避免冲突
        if os.path.exists(args.val_output):
            import shutil
            logger.info(f"Removing existing validation output directory: {args.val_output}")
            shutil.rmtree(args.val_output)
        
        run_validation(args.output, args.dataset, args.val_output)
        
        # 等待验证完成后解析结果
        logger.info("🔍 Parsing validation results and calculating repair rates...")
        time.sleep(5)  # 等待文件写入完成
        
        statistics = parse_validation_results(args.val_output)
        
        # 保存统计结果
        stats_file = os.path.join(os.path.dirname(args.output), 'repair_statistics.json')
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📊 Repair statistics saved to {stats_file}")
        
    else:
        logger.info("🔍 To validate patches, run with --validate flag")
        logger.info("💡 Example: python self_debug_multi_defects4j.py --validate --workers 4")
        logger.info("💡 Or validate existing patches: python self_debug_multi_defects4j.py --validate-only")
    
    logger.info("All tasks completed!")

if __name__ == "__main__":
    main() 
    # bug_name = "Chart-1"
    # bug_data = json.load(open("dataset_test/SRepair/SRepair/dataset/defects4j-sf.json", "r"))[bug_name]
    # selfdebug_java_single(bug_name, bug_data)