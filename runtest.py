from utils import run_check_function
import json

code_to_test = """
def sort_numbers(numbers: str) -> str:
    value_map = create_value_map()
    words = split_input(numbers)
    valid_words = filter_valid_words(words)
    numeric_values = convert_words_to_numbers(valid_words, value_map)
    
    # Sort the numeric values
    numeric_values.sort()  # Sort the values
    
    # Create a reversed mapping from numeric values back to words for final output
    reversed_value_map = {v: k for k, v in value_map.items()}
    sorted_words = [reversed_value_map[v] for v in numeric_values]
    
    # Join the sorted words into a string
    return ' '.join(sorted_words)

def create_value_map() -> dict:
    return {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9}

def split_input(numbers: str) -> list:
    return numbers.split(' ')

def filter_valid_words(words: list) -> list:
    return [x for x in words if x]

def convert_words_to_numbers(valid_words: list, value_map: dict) -> list:
    return [value_map[word] for word in valid_words if word in value_map]

def join_numeric_values(numeric_values: list) -> str:
    return ' '.join(map(str, numeric_values))
"""
if __name__ == "__main__":
    with open("data/humanevalfix/humanevalpack.jsonl", "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i == 20:
                data = json.loads(line.strip())
                break
        else:
            print("文件中没有第3行")
    funcname = data["entry_point"]
    check_code = data["test"]
    run_check_function(funcname, check_code, code_to_test)