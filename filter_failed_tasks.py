import json
from typing import Set, List

def filter_failed_tasks(file1_path: str, file2_path: str):
    """筛选两个JSON文件中的测试失败任务"""
    
    # 加载文件
    try:
        with open(file1_path, 'r', encoding='utf-8') as f:
            data1 = json.load(f)
        with open(file2_path, 'r', encoding='utf-8') as f:
            data2 = json.load(f)
    except FileNotFoundError as e:
        print(f"文件不存在: {e}")
        return
    except json.JSONDecodeError as e:
        print(f"JSON格式错误: {e}")
        return
    
    # 获取测试失败的任务ID
    failed_tasks_1 = set()
    failed_tasks_2 = set()
    
    # 从文件1中提取失败任务
    for task in data1.get('details', []):
        if task.get('test_passed') == False:
            failed_tasks_1.add(task['task_id'])
    
    # 从文件2中提取失败任务
    for task in data2.get('details', []):
        if task.get('test_passed') == False:
            failed_tasks_2.add(task['task_id'])
    
    # 1. 两个文件中都失败的任务
    both_failed = failed_tasks_1 & failed_tasks_2
    
    # 2. 只在一个文件中失败的任务（对称差集）
    only_once_failed = failed_tasks_1 ^ failed_tasks_2
    
    # 输出结果
    print("=== 筛选结果 ===")
    print(f"分析文件: {file1_path} 和 {file2_path}")
    print()
    
    print(f"两个文件中都测试失败的任务 ({len(both_failed)}个):")
    if both_failed:
        for task_id in sorted(both_failed):
            print(f"  {task_id}")
    else:
        print("  无")
    print()
    
    print(f"只在一个文件中测试失败的任务 ({len(only_once_failed)}个):")
    if only_once_failed:
        for task_id in sorted(only_once_failed):
            # 判断是在哪个文件中失败的
            if task_id in failed_tasks_1:
                source = "文件1"
            else:
                source = "文件2"
            print(f"  {task_id} (仅在{source}中失败)")
    else:
        print("  无")
    
    return {
        "both_failed": sorted(list(both_failed)),
        "only_once_failed": sorted(list(only_once_failed))
    }

def save_filtered_results(file1_path: str, file2_path: str, output_file: str):
    """保存筛选结果到文件"""
    
    # 获取筛选结果
    results = filter_failed_tasks(file1_path, file2_path)
    
    if results:
        # 保存到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n筛选结果已保存到: {output_file}")

if __name__ == "__main__":
    # 定义文件路径
    file1 = "debug_results_20250707_180431.json"
    file2 = "debug_results_20250707_193537.json"
    output_file = "filtered_failed_tasks.json"
    
    # 执行筛选
    save_filtered_results(file1, file2, output_file) 