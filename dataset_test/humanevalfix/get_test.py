import json

def extract_tests(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:
        
        for line in infile:
            try:
                data = json.loads(line)
                # 提取所需字段
                task_id = data.get("task_id", "")
                entry_point = data.get("entry_point", "")
                test = data.get("test", "")
                example_test = data.get("example_test", "")
                declaration = data.get("declaration", "")
                buggy_solution = data.get("buggy_solution", "")
                buggy_code = declaration + buggy_solution
                
                # 写入新文件
                outfile.write(f"# Task ID: {task_id}\n")
                outfile.write(f"# Function: {entry_point}\n\n")
                outfile.write("# Buggy code:\n")
                outfile.write(buggy_code + "\n\n")
                outfile.write("# Test cases:\n")
                outfile.write(test + "\n\n")
                outfile.write("# Example test:\n")
                outfile.write(example_test + "\n")
                outfile.write("-" * 80 + "\n\n")
                
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON line: {e}")
                continue

# 使用示例
input_filename = "humanevalpack.jsonl"
output_filename = "extracted_tests.txt"
extract_tests(input_filename, output_filename)

print(f"Tests extracted and saved to {output_filename}")