#!/usr/bin/env python3
"""
使用selfdebug架构处理defects4j-sf数据集中的Java代码
替代SRepair中的gen_solution和gen_patch，并使用sf_val_d4j验证正确率
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

def process_defects4j_dataset(dataset_path: str, output_path: str, limit: int = None) -> Dict:
    """
    处理整个defects4j数据集
    Args:
        dataset_path: 数据集路径
        output_path: 输出路径
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
    
    results = {}
    patches_generated = 0
    
    for i, bug_name in enumerate(bug_names, 1):
        logger.info(f"=== Processing bug {i}/{len(bug_names)}: {bug_name} ===")
        
        try:
            corrected_code = selfdebug_java_single(bug_name, dataset[bug_name])
            
            if corrected_code and corrected_code != dataset[bug_name]['buggy']:
                results[bug_name] = {
                    'patches': [corrected_code],
                    'original_buggy': dataset[bug_name]['buggy'],
                    'bug_info': {
                        'loc': dataset[bug_name]['loc'],
                        'start': dataset[bug_name]['start'],
                        'end': dataset[bug_name]['end']
                    }
                }
                patches_generated += 1
                logger.info(f"📝 Generated patch for {bug_name} (validation required)")
            else:
                logger.warning(f"❌ No patch generated for {bug_name}")
                # 为了能够进行验证，即使失败也要记录原始代码
                results[bug_name] = {
                    'patches': [dataset[bug_name]['buggy']],  # 使用原始代码
                    'original_buggy': dataset[bug_name]['buggy'],
                    'bug_info': {
                        'loc': dataset[bug_name]['loc'],
                        'start': dataset[bug_name]['start'],
                        'end': dataset[bug_name]['end']
                    }
                }
        
        except Exception as e:
            logger.error(f"Error processing {bug_name}: {e}")
            # 记录失败的情况
            results[bug_name] = {
                'patches': [dataset[bug_name]['buggy']],  # 使用原始代码
                'original_buggy': dataset[bug_name]['buggy'],
                'bug_info': {
                    'loc': dataset[bug_name]['loc'],
                    'start': dataset[bug_name]['start'],
                    'end': dataset[bug_name]['end']
                }
            }
    
    logger.info(f"=== Processing completed ===")
    logger.info(f"Total processed: {len(bug_names)}")
    logger.info(f"Patches generated: {patches_generated}")
    logger.info(f"Patch generation rate: {patches_generated/len(bug_names)*100:.2f}%")
    
    # 保存结果
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
    parser.add_argument('--val-output', type=str, default='dataset_test/SRepair/results/sf/defects4j_validation_results',
                       help='Output directory for validation results')
    parser.add_argument('--limit', '-l', type=int, default=None,
                       help='Limit the number of bugs to process (useful for debugging)')
    
    args = parser.parse_args()
    
    # 设置日志
    logger.info("Starting defects4j static analysis processing...")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Validate: {args.validate}")
    if args.limit:
        logger.info(f"Processing limit: {args.limit} bugs")
    
    # 检查输入文件
    if not os.path.exists(args.dataset):
        logger.error(f"Dataset file not found: {args.dataset}")
        return
    
    # 处理数据集
    start_time = time.time()
    results = process_defects4j_dataset(args.dataset, args.output, args.limit)
    processing_time = time.time() - start_time
    
    logger.info(f"Patch generation completed in {processing_time:.2f} seconds")
    
    # 运行验证
    if args.validate:
        logger.info("🔍 Starting validation with sf_val_d4j...")
        run_validation(args.output, args.dataset, args.val_output)
    else:
        logger.info("🔍 To validate patches, run with --validate flag")
        logger.info("💡 Example: python selfdebug_java_defects4j.py --validate --val-output validation_results")
    
    logger.info("All tasks completed!")

if __name__ == "__main__":
    main() 
    # bug_name = "Chart-1"
    # bug_data = json.load(open("dataset_test/SRepair/SRepair/dataset/defects4j-sf.json", "r"))[bug_name]
    # selfdebug_java_single(bug_name, bug_data)