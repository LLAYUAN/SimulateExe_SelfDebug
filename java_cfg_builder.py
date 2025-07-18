import subprocess
import sys
import json
import tempfile
import os
from pathlib import Path
from loguru import logger
from typing import Dict, List, Set, Optional, Tuple, Any
import copy
import re


class JavaCFG:
    def __init__(self, source_path: str, target_method: str = None, target_class: str = None):
        """
        改进的Java函数级CFG构建器
        Args:
            source_path: Java源代码文件路径
            target_method: 目标方法名（不包含参数），如果不指定则使用第一个方法
            target_class: 目标类名，如果不指定则使用第一个类
        """
        # #logger.info(f"🚀🚀🚀 JavaCFG.__init__ called with source_path={source_path}")
        
        self.source_path = source_path
        self.source_code = Path(source_path).read_text(encoding='utf-8')
        self.source_lines = self.source_code.splitlines()
        
        # #logger.info(f"📖 Read {len(self.source_lines)} lines from Java file")
        
        # Java关键字集合
        self.java_keywords = {
            'abstract', 'assert', 'boolean', 'break', 'byte', 'case', 'catch', 'char',
            'class', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum',
            'extends', 'final', 'finally', 'float', 'for', 'goto', 'if', 'implements',
            'import', 'instanceof', 'int', 'interface', 'long', 'native', 'new',
            'package', 'private', 'protected', 'public', 'return', 'short', 'static',
            'strictfp', 'super', 'switch', 'synchronized', 'this', 'throw', 'throws',
            'transient', 'try', 'void', 'volatile', 'while'
        }
        
        # 解析Java AST
        self.java_ast = self._parse_java_ast()
        
        # 解析所有类和方法
        self.all_classes = self._parse_all_classes()
        self.all_methods = self._parse_all_methods()
        
        # 确定目标类和方法
        if target_class:
            if target_class not in self.all_classes:
                raise ValueError(f"目标类 '{target_class}' 在源代码中未找到")
            self.target_class = target_class
        else:
            self.target_class = list(self.all_classes.keys())[0] if self.all_classes else None
            
        if target_method:
            if target_method not in self.all_methods:
                raise ValueError(f"目标方法 '{target_method}' 在源代码中未找到")
            self.target_method = target_method
        else:
            # 从目标类中选择第一个方法
            class_methods = [method for method in self.all_methods.keys() 
                           if self.all_methods[method]['class'] == self.target_class]
            self.target_method = class_methods[0] if class_methods else None
            
        if not self.target_method:
            raise ValueError("未找到任何方法定义")
            
        # #logger.info(f"目标类: {self.target_class}")
        # #logger.info(f"目标方法: {self.target_method}")
        
        # 构建CFG
        self.blocks = []
        self.connections = []
        self.method_signature = self._get_method_signature(self.target_method)
        
        # 跟踪当前的循环和异常处理上下文
        self.loop_stack = []  # 用于处理break/continue
        self.try_stack = []   # 用于处理异常
        
        # 构建完整的CFG
        self._build_complete_cfg()
        
        # 生成文本表示
        self.cfg_text = self._generate_cfg_text()
        self.block_num = len(self.blocks)
        self.block_code_list = [block['code'] for block in self.blocks]
    
    def _parse_java_ast(self) -> Dict:
        """使用改进的Java解析方法"""
        return self._improved_parse()
    
    def _improved_parse(self) -> Dict:
        """改进的Java代码解析方法"""
        classes = {}
        methods = {}
        
        # 解析类定义 - 更精确的正则表达式
        class_pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+(\w+)(?:\s+extends\s+\w+)?(?:\s+implements\s+[\w,\s]+)?\s*\{'
        for match in re.finditer(class_pattern, self.source_code):
            class_name = match.group(1)
            classes[class_name] = {
                'name': class_name,
                'start_line': self.source_code[:match.start()].count('\n') + 1,
                'start_pos': match.start(),
                'end_pos': self._find_class_end(match.start())
            }
        
        # 解析方法定义 - 更精确的正则表达式
        method_pattern = r'(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:final\s+)?(?:\w+(?:\[\])?)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{'
        for match in re.finditer(method_pattern, self.source_code):
            method_name = match.group(1)
            
            # 过滤Java关键字和常见的非方法名
            if method_name in self.java_keywords:
                continue
            
            method_line = self.source_code[:match.start()].count('\n') + 1
            
            # 找到方法所属的类
            belonging_class = None
            for class_name, class_info in classes.items():
                if (match.start() > class_info['start_pos'] and 
                    match.start() < class_info['end_pos']):
                    belonging_class = class_name
                    break
            
            if belonging_class:  # 只添加属于某个类的方法
                methods[method_name] = {
                    'name': method_name,
                    'class': belonging_class,
                    'start_line': method_line,
                    'body_start': match.end(),
                    'body_end': self._find_method_end(match.start())
                }
        
        return {
            'classes': classes,
            'methods': methods,
            'source_lines': self.source_lines
        }
    
    def _find_class_end(self, start_pos: int) -> int:
        """找到类定义的结束位置"""
        brace_count = 0
        in_class = False
        
        for i in range(start_pos, len(self.source_code)):
            char = self.source_code[i]
            if char == '{':
                in_class = True
                brace_count += 1
            elif char == '}' and in_class:
                brace_count -= 1
                if brace_count == 0:
                    return i
        
        return len(self.source_code)
    
    def _find_method_end(self, start_pos: int) -> int:
        """找到方法定义的结束位置"""
        brace_count = 0
        in_method = False
        
        for i in range(start_pos, len(self.source_code)):
            char = self.source_code[i]
            if char == '{':
                in_method = True
                brace_count += 1
            elif char == '}' and in_method:
                brace_count -= 1
                if brace_count == 0:
                    return i
        
        return len(self.source_code)
    
    def _parse_all_classes(self) -> Dict[str, Dict]:
        """解析所有类定义"""
        return self.java_ast.get('classes', {})
    
    def _parse_all_methods(self) -> Dict[str, Dict]:
        """解析所有方法定义"""
        return self.java_ast.get('methods', {})
    
    def _get_method_signature(self, method_name: str) -> str:
        """获取带参数的方法签名"""
        if method_name in self.all_methods:
            method_info = self.all_methods[method_name]
            class_name = method_info.get('class', '')
            return f"{class_name}.{method_name}()"
        return f"{method_name}()"
    
    def _build_complete_cfg(self):
        """构建完整的CFG"""
        # #logger.info("🏗️🏗️🏗️ Building complete CFG...")
        visited_methods = set()
        self._build_method_cfg(self.target_method, visited_methods)
        
        # #logger.info(f"📊 Total blocks created: {len(self.blocks)}")
        # #logger.info(f"📊 Total connections before control structures: {len(self.connections)}")
        
        # 在所有方法处理完后，统一添加控制结构连接
        # #logger.info("🔗 Adding control structure connections...")
        self._add_java_control_structure_connections()
        
        # #logger.info(f"📊 Total connections after control structures: {len(self.connections)}")
    
    def _build_method_cfg(self, method_name: str, visited_methods: Set[str]):
        """递归构建方法的CFG"""
        if method_name in visited_methods:
            # #logger.warning(f"检测到递归调用: {method_name}")
            return
            
        if method_name not in self.all_methods:
            # #logger.warning(f"方法 {method_name} 未找到定义，跳过")
            return
            
        visited_methods.add(method_name)
        method_info = self.all_methods[method_name]
        
        # #logger.info(f"🏗️ 处理方法: {method_name}")
        # #logger.info(f"📋 Method info keys: {list(method_info.keys())}")
        # #logger.info(f"📋 Method info: body_start={method_info['body_start']}, body_end={method_info['body_end']}")
        
        # 从源代码中提取方法体语句
        body_start = method_info['body_start']
        body_end = method_info['body_end']
        method_body = self.source_code[body_start:body_end]
        
        # #logger.info(f"📝 Method body content: {method_body[:200]}...")
        
        # 将方法体分解为语句
        statements = self._extract_statements_from_body(method_body)
        # #logger.info(f"📋 方法 {method_name} 包含 {len(statements)} 个语句")
        
        # 显示前几个语句
        # for i, stmt in enumerate(statements[:10]):
        #     #logger.info(f"📝 语句 {i}: '{stmt.strip()}'")
        
        # 解析方法体
        main_blocks = self._process_java_statements(statements, visited_methods, method_name)
        
        # 处理方法调用
        self._process_method_calls_in_blocks(visited_methods)
        
        visited_methods.remove(method_name)
    
    def _extract_statements_from_body(self, method_body: str) -> List[str]:
        """从方法体字符串中提取语句"""
        # #logger.info(f"🔍 Extracting statements from method body...")
        
        # 去掉开头和结尾的大括号
        method_body = method_body.strip()
        if method_body.startswith('{'):
            method_body = method_body[1:]
        if method_body.endswith('}'):
            method_body = method_body[:-1]
        
        # 按行分割
        lines = method_body.split('\n')
        statements = []
        
        current_statement = ""
        brace_count = 0
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('/*') or line.startswith('*'):
                continue
            
            # 计算大括号
            brace_count += line.count('{') - line.count('}')
            
            # 添加到当前语句
            if current_statement:
                current_statement += " " + line
            else:
                current_statement = line
            
            # 如果遇到分号且不在大括号内，则结束当前语句
            if (line.endswith(';') or line.endswith('{')) and brace_count >= 0:
                statements.append(current_statement)
                current_statement = ""
            # 如果遇到单独的右大括号，也结束语句
            elif line == '}' and brace_count >= 0:
                if current_statement:
                    statements.append(current_statement)
                    current_statement = ""
        
        # 处理最后一个语句
        if current_statement:
            statements.append(current_statement)
        
        # #logger.info(f"✅ Extracted {len(statements)} statements")
        return statements

    
    def _extract_method_body(self, method_info: Dict) -> List[str]:
        """提取方法体的语句"""
        start_line = method_info['start_line']
        
        # 找到方法体的开始和结束
        lines = []
        brace_count = 0
        in_method_body = False
        
        for i, line in enumerate(self.source_lines[start_line - 1:], start=start_line):
            stripped = line.strip()
            
            # 跳过空行和注释
            if not stripped or stripped.startswith('//') or stripped.startswith('/*'):
                continue
            
            if not in_method_body and '{' in line:
                in_method_body = True
                brace_count += line.count('{') - line.count('}')
                # 如果开始行有代码（除了{），也要包含
                content_before_brace = line[:line.index('{')].strip()
                if content_before_brace and not content_before_brace.endswith(')'):
                    lines.append(line)
                continue
            
            if in_method_body:
                brace_count += line.count('{') - line.count('}')
                if brace_count > 0:
                    lines.append(line)
                else:
                    # 方法结束
                    break
        
        return lines
    
    def _process_java_statements(self, statements: List[str], visited_methods: Set[str], method_name: str) -> List[int]:
        """处理Java语句列表"""
        block_ids = []
        
        i = 0
        while i < len(statements):
            stmt = statements[i].strip()
            if not stmt:
                i += 1
                continue
            
            # 根据语句类型处理
            stmt_blocks, consumed_lines = self._process_single_java_statement(
                statements[i:], visited_methods, method_name, i + 1)
            block_ids.extend(stmt_blocks)
            i += consumed_lines
        
        # 建立顺序连接
        self._connect_sequential_blocks(block_ids)
        
        return block_ids
    
    def _process_single_java_statement(self, statements: List[str], visited_methods: Set[str], 
                                     method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理单个Java语句"""
        stmt = statements[0].strip()
        
        # 跳过只有大括号的行
        if stmt in ['{', '}']:
            return [], 1
        
        # if语句
        if stmt.startswith('if'):
            return self._process_java_if(statements, visited_methods, method_name, line_number)
        # else语句（单独的else）
        elif stmt.startswith('} else if') or stmt.startswith('else if'):
            return self._process_java_else_if(statements, visited_methods, method_name, line_number)
        elif stmt.startswith('} else') or stmt.startswith('else'):
            return self._process_java_else(statements, visited_methods, method_name, line_number)
        # for循环
        elif stmt.startswith('for'):
            return self._process_java_for(statements, visited_methods, method_name, line_number)
        # while循环
        elif stmt.startswith('while'):
            return self._process_java_while(statements, visited_methods, method_name, line_number)
        # do-while循环
        elif stmt.startswith('do'):
            return self._process_java_do_while(statements, visited_methods, method_name, line_number)
        # switch语句
        elif stmt.startswith('switch'):
            return self._process_java_switch(statements, visited_methods, method_name, line_number)
        # try语句
        elif stmt.startswith('try'):
            return self._process_java_try(statements, visited_methods, method_name, line_number)
        # catch语句
        elif stmt.startswith('} catch') or stmt.startswith('catch'):
            return self._process_java_catch(statements, visited_methods, method_name, line_number)
        # finally语句
        elif stmt.startswith('} finally') or stmt.startswith('finally'):
            return self._process_java_finally(statements, visited_methods, method_name, line_number)
        # return语句
        elif stmt.startswith('return'):
            return self._process_java_return(statements, visited_methods, method_name, line_number)
        # break语句
        elif stmt.startswith('break'):
            return self._process_java_break(stmt, method_name, line_number)
        # continue语句
        elif stmt.startswith('continue'):
            return self._process_java_continue(stmt, method_name, line_number)
        # throw语句
        elif stmt.startswith('throw'):
            return self._process_java_throw(stmt, method_name, line_number)
        # 变量声明或赋值
        else:
            return self._process_java_assignment(stmt, visited_methods, method_name, line_number)
    
    def _process_java_if(self, statements: List[str], visited_methods: Set[str], 
                        method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java if语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析if条件
        if_line = statements[0].strip()
        condition = self._extract_condition(if_line)
        
        # 创建if块
        if_block_id = self._create_java_block(if_line, 'if_statement', method_name, line_number, {
            'condition': condition,
            'is_control_structure': True  # 标记为控制结构，避免sequential连接
        })
        all_blocks.append(if_block_id)
        consumed_lines += 1
        
        # 处理if体
        then_statements, then_consumed = self._extract_block_statements(statements[1:])
        then_blocks = []
        if then_statements:
            then_blocks = self._process_java_statements(then_statements, visited_methods, method_name)
            all_blocks.extend(then_blocks)
        consumed_lines += then_consumed
        
        # 建立连接 - 只创建condition_true连接，condition_false将在_add_control_structure_connections中处理
        if then_blocks:
            self._add_connection(if_block_id, then_blocks[0], f'condition_true:{condition}')
        
        # 存储if块信息供后续处理condition_false连接
        self.blocks[if_block_id]['then_blocks'] = then_blocks
        
        return all_blocks, consumed_lines
    
    def _process_java_else_if(self, statements: List[str], visited_methods: Set[str], 
                             method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java else if语句"""
        # 递归处理as if语句
        else_if_line = statements[0].strip()
        # 提取else if中的if部分
        if_part = else_if_line.replace('} else if', 'if').replace('else if', 'if')
        modified_statements = [if_part] + statements[1:]
        return self._process_java_if(modified_statements, visited_methods, method_name, line_number)
    
    def _process_java_else(self, statements: List[str], visited_methods: Set[str], 
                          method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java else语句"""
        all_blocks = []
        consumed_lines = 1  # else行本身
        
        # 处理else体
        else_statements, else_consumed = self._extract_block_statements(statements[1:])
        if else_statements:
            else_blocks = self._process_java_statements(else_statements, visited_methods, method_name)
            all_blocks.extend(else_blocks)
        consumed_lines += else_consumed
        
        return all_blocks, consumed_lines
    
    def _process_java_for(self, statements: List[str], visited_methods: Set[str], 
                         method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java for循环（参考Python CFG builder思路）"""
        all_blocks = []
        
        # 1. 创建for循环头部块
        for_line = statements[0].strip()
        condition = self._extract_condition(for_line)
        
        for_block_id = self._create_java_block(for_line, 'for_statement', method_name, line_number, {
            'condition': condition,
            'is_control_structure': True
        })
        all_blocks.append(for_block_id)
        
        # #logger.info(f"🔄 Created for loop header block {for_block_id}: '{for_line}'")
        
        # 将for循环推入栈
        self.loop_stack.append({
            'type': 'for',
            'header_id': for_block_id,
            'line': for_line
        })
        
        # 2. 提取循环体语句
        body_statements, body_consumed = self._extract_java_for_body(statements)
        # #logger.info(f"📋 Extracted {len(body_statements)} body statements")
        
        # 3. 处理循环体语句
        body_blocks = []
        if body_statements:
            body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
            all_blocks.extend(body_blocks)
            # #logger.info(f"🔗 Created {len(body_blocks)} body blocks: {body_blocks}")
        
        # 4. 建立连接（参考Python CFG思路）
        self._connect_java_for_loop(for_block_id, body_blocks, condition)
        
        # 存储for块信息
        self.blocks[for_block_id]['body_blocks'] = body_blocks
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        consumed_lines = 1 + body_consumed  # for头 + 循环体
        return all_blocks, consumed_lines
    
    def _extract_java_for_body(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取Java for循环体语句"""
        # #logger.info(f"🔍 Extracting for body from {len(statements)} total statements")
        # #logger.info(f"📝 Available statements: {[s.strip() for s in statements[:5]]}")
        
        for_header = statements[0].strip()
        
        # 如果for头包含开大括号，从后续语句中提取循环体
        if '{' in for_header:
            body_statements = []
            brace_count = for_header.count('{') - for_header.count('}')
            consumed_lines = 0
            
            # #logger.info(f"🔢 Initial brace_count from header: {brace_count}")
            
            # 从第二行开始提取循环体
            i = 1
            while i < len(statements) and brace_count > 0:
                stmt = statements[i]
                stmt_stripped = stmt.strip()
                
                # #logger.debug(f"🔍 Processing statement {i}: '{stmt_stripped}' (brace_count: {brace_count})")
                
                if not stmt_stripped:
                    i += 1
                    consumed_lines += 1
                    continue
                
                # 计算大括号
                open_braces = stmt.count('{')
                close_braces = stmt.count('}')
                brace_count += open_braces - close_braces
                
                #logger.debug(f"🔢 Statement {i}: +{open_braces} -{close_braces} = {brace_count}")
                
                if brace_count > 0:
                    body_statements.append(stmt)
                    #logger.info(f"📋 Added body statement: '{stmt_stripped}'")
                elif brace_count == 0 and stmt_stripped == '}':
                    #logger.info(f"✅ Found closing brace, ending body extraction")
                    consumed_lines += 1
                    break
                
                i += 1
                consumed_lines += 1
            
            #logger.info(f"✅ Extracted {len(body_statements)} for body statements")
            return body_statements, consumed_lines
        else:
            # for头没有大括号，可能是单行循环
            #logger.info(f"🔄 For header has no brace, using _extract_block_statements")
            body_statements, body_consumed = self._extract_block_statements(statements[1:])
            return body_statements, body_consumed
    
    def _connect_java_for_loop(self, for_block_id: int, body_blocks: List[int], condition: str):
        """建立Java for循环的连接（参考Python CFG思路）"""
        # for -> 循环体（condition_true）
        if body_blocks:
            #logger.info(f"🔗 Creating for_match connection: {for_block_id} -> {body_blocks[0]}")
            self._add_connection(for_block_id, body_blocks[0], f'condition_true:{condition}')
        
        # condition_false连接会在后续的_add_loop_condition_false_connections中处理
    

    
    def _process_java_while(self, statements: List[str], visited_methods: Set[str], 
                           method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java while循环"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析while语句
        while_line = statements[0].strip()
        condition = self._extract_condition(while_line)
        
        # 创建while块
        while_block_id = self._create_java_block(while_line, 'while_statement', method_name, line_number, {
            'condition': condition,
            'is_control_structure': True  # 标记为控制结构，避免sequential连接
        })
        all_blocks.append(while_block_id)
        consumed_lines += 1
        
        # 将while循环推入栈
        self.loop_stack.append({
            'type': 'while',
            'header_id': while_block_id,
            'line': while_line
        })
        
        # 处理循环体
        body_statements, body_consumed = self._extract_block_statements(statements[1:])
        body_blocks = []
        if body_statements:
            body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
            all_blocks.extend(body_blocks)
            
            # 建立连接 - condition_true进入循环体
            self._add_connection(while_block_id, body_blocks[0], f'condition_true:{condition}')
        
        consumed_lines += body_consumed
        
        # 存储while块信息供后续处理condition_false连接
        self.blocks[while_block_id]['body_blocks'] = body_blocks
        # 确保while循环块不会被误认为是if块
        if 'then_blocks' in self.blocks[while_block_id]:
            del self.blocks[while_block_id]['then_blocks']
        
        # 弹出循环栈
        self.loop_stack.pop()
        
        return all_blocks, consumed_lines
    
    def _process_java_do_while(self, statements: List[str], visited_methods: Set[str], 
                              method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java do-while循环"""
        all_blocks = []
        consumed_lines = 0
        
        # 创建do块
        do_line = statements[0].strip()
        do_block_id = self._create_java_block(do_line, 'do_statement', method_name, line_number)
        all_blocks.append(do_block_id)
        consumed_lines += 1
        
        # 处理do体
        body_statements, body_consumed = self._extract_do_while_body(statements[1:])
        if body_statements:
            body_blocks = self._process_java_statements(body_statements, visited_methods, method_name)
            all_blocks.extend(body_blocks)
            
            # do -> 循环体
            self._add_connection(do_block_id, body_blocks[0], 'sequential')
        
        consumed_lines += body_consumed
        
        # 处理while条件
        while_line_index = consumed_lines
        if while_line_index < len(statements):
            while_line = statements[while_line_index].strip()
            if while_line.startswith('} while'):
                condition = self._extract_condition(while_line)
                while_block_id = self._create_java_block(while_line, 'while_condition', method_name, 
                                                        line_number + while_line_index, {'condition': condition})
                all_blocks.append(while_block_id)
                consumed_lines += 1
                
                # 建立连接
                if body_statements:
                    last_body_block = body_blocks[-1] if body_blocks else do_block_id
                    self._add_connection(last_body_block, while_block_id, 'sequential')
                    self._add_connection(while_block_id, do_block_id, f'condition_true:{condition}')
        
        return all_blocks, consumed_lines
    
    def _extract_do_while_body(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取do-while循环体"""
        body_statements = []
        consumed_lines = 0
        brace_count = 0
        
        for i, line in enumerate(statements):
            stripped = line.strip()
            
            if stripped.startswith('} while'):
                break
            
            # 计算大括号
            brace_count += line.count('{') - line.count('}')
            
            if stripped == '{':
                consumed_lines += 1
                continue
            elif brace_count >= 0:
                body_statements.append(line)
                consumed_lines += 1
        
        return body_statements, consumed_lines
    
    def _process_java_switch(self, statements: List[str], visited_methods: Set[str], 
                            method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java switch语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 解析switch语句
        switch_line = statements[0].strip()
        condition = self._extract_condition(switch_line)
        
        # 创建switch块
        switch_block_id = self._create_java_block(switch_line, 'switch_statement', method_name, line_number, {
            'condition': condition
        })
        all_blocks.append(switch_block_id)
        consumed_lines += 1
        
        # 解析switch体
        switch_body, switch_consumed = self._extract_switch_body(statements[1:])
        consumed_lines += switch_consumed
        
        # 处理case和default
        case_blocks = []
        i = 0
        while i < len(switch_body):
            line = switch_body[i].strip()
            if line.startswith('case') or line.startswith('default'):
                # 创建case/default块
                case_block_id = self._create_java_block(line, 'case_statement', method_name, 
                                                       line_number + consumed_lines + i)
                all_blocks.append(case_block_id)
                case_blocks.append((case_block_id, line))
                i += 1
                
                # 处理case体
                case_statements = []
                while i < len(switch_body):
                    case_line = switch_body[i].strip()
                    if case_line.startswith(('case', 'default')):
                        break
                    if case_line and case_line != '}':
                        case_statements.append(switch_body[i])
                    i += 1
                
                if case_statements:
                    case_body_blocks = self._process_java_statements(case_statements, visited_methods, method_name)
                    all_blocks.extend(case_body_blocks)
                    
                    # case -> case体
                    if case_body_blocks:
                        self._add_connection(case_block_id, case_body_blocks[0], 'sequential')
            else:
                i += 1
        
        # 建立switch连接
        for case_block_id, case_line in case_blocks:
            if case_line.startswith('case'):
                case_value = case_line.split()[1].rstrip(':')
                self._add_connection(switch_block_id, case_block_id, f'case_match:{case_value}')
            elif case_line.startswith('default'):
                self._add_connection(switch_block_id, case_block_id, 'default_case')
        
        return all_blocks, consumed_lines
    
    def _extract_switch_body(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取switch体"""
        body_statements = []
        consumed_lines = 0
        brace_count = 0
        
        for i, line in enumerate(statements):
            stripped = line.strip()
            
            # 计算大括号
            brace_count += line.count('{') - line.count('}')
            
            if stripped == '{':
                consumed_lines += 1
                continue
            elif stripped == '}' and brace_count == 0:
                consumed_lines += 1
                break
            elif brace_count > 0:
                body_statements.append(line)
                consumed_lines += 1
        
        return body_statements, consumed_lines
    
    def _process_java_try(self, statements: List[str], visited_methods: Set[str], 
                         method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java try语句"""
        all_blocks = []
        consumed_lines = 0
        
        # 创建try块
        try_line = statements[0].strip()
        try_block_id = self._create_java_block(try_line, 'try_statement', method_name, line_number)
        all_blocks.append(try_block_id)
        consumed_lines += 1
        
        # 处理try体
        try_statements, try_consumed = self._extract_block_statements(statements[1:])
        if try_statements:
            try_blocks = self._process_java_statements(try_statements, visited_methods, method_name)
            all_blocks.extend(try_blocks)
            
            # try -> try体
            if try_blocks:
                self._add_connection(try_block_id, try_blocks[0], 'sequential')
        
        consumed_lines += try_consumed
        
        return all_blocks, consumed_lines
    
    def _process_java_catch(self, statements: List[str], visited_methods: Set[str], 
                           method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java catch语句"""
        all_blocks = []
        consumed_lines = 0
        
        catch_line = statements[0].strip()
        catch_block_id = self._create_java_block(catch_line, 'catch_statement', method_name, line_number)
        all_blocks.append(catch_block_id)
        consumed_lines += 1
        
        # 处理catch体
        catch_statements, catch_consumed = self._extract_block_statements(statements[1:])
        if catch_statements:
            catch_blocks = self._process_java_statements(catch_statements, visited_methods, method_name)
            all_blocks.extend(catch_blocks)
            
            # catch -> catch体
            if catch_blocks:
                self._add_connection(catch_block_id, catch_blocks[0], 'sequential')
        
        consumed_lines += catch_consumed
        
        return all_blocks, consumed_lines
    
    def _process_java_finally(self, statements: List[str], visited_methods: Set[str], 
                             method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java finally语句"""
        all_blocks = []
        consumed_lines = 0
        
        finally_line = statements[0].strip()
        finally_block_id = self._create_java_block(finally_line, 'finally_statement', method_name, line_number)
        all_blocks.append(finally_block_id)
        consumed_lines += 1
        
        # 处理finally体
        finally_statements, finally_consumed = self._extract_block_statements(statements[1:])
        if finally_statements:
            finally_blocks = self._process_java_statements(finally_statements, visited_methods, method_name)
            all_blocks.extend(finally_blocks)
            
            # finally -> finally体
            if finally_blocks:
                self._add_connection(finally_block_id, finally_blocks[0], 'sequential')
        
        consumed_lines += finally_consumed
        
        return all_blocks, consumed_lines
    
    def _process_java_return(self, statements: List[str], visited_methods: Set[str], 
                            method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java return语句"""
        return_line = statements[0].strip()
        block_id = self._create_java_block(return_line, 'return', method_name, line_number)
        return [block_id], 1
    
    def _process_java_break(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java break语句"""
        block_id = self._create_java_block(stmt, 'break', method_name, line_number)
        
        # 连接到最近的循环外部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            self.blocks[block_id]['break_target'] = current_loop
        
        return [block_id], 1
    
    def _process_java_continue(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java continue语句"""
        block_id = self._create_java_block(stmt, 'continue', method_name, line_number)
        
        # 连接到最近的循环头部
        if self.loop_stack:
            current_loop = self.loop_stack[-1]
            self._add_connection(block_id, current_loop['header_id'], 'continue')
        
        return [block_id], 1
    
    def _process_java_throw(self, stmt: str, method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java throw语句"""
        block_id = self._create_java_block(stmt, 'throw', method_name, line_number)
        return [block_id], 1
    
    def _process_java_assignment(self, stmt: str, visited_methods: Set[str], 
                                method_name: str, line_number: int) -> Tuple[List[int], int]:
        """处理Java赋值或表达式语句"""
        # 检测语句类型
        if ('=' in stmt and 
            not any(op in stmt for op in ['==', '!=', '<=', '>=', '++', '--']) and
            not stmt.strip().endswith(';')):
            block_type = 'assignment'
        else:
            block_type = 'expression'
        
        block_id = self._create_java_block(stmt, block_type, method_name, line_number)
        return [block_id], 1
    
    def _create_java_block(self, code: str, block_type: str, method_name: str, 
                          line_number: int, extra_info: Dict = None) -> int:
        """创建一个新的Java block"""
        block_id = len(self.blocks)
        
        block_info = {
            'id': block_id,
            'type': block_type,
            'code': code.strip(),
            'line_number': line_number,
            'method': method_name,
            'method_calls': self._extract_java_method_calls(code)
        }
        
        if extra_info:
            block_info.update(extra_info)
            
        self.blocks.append(block_info)
        
        return block_id
    
    def _extract_condition(self, line: str) -> str:
        """提取条件表达式"""
        # 匹配完整的条件表达式，处理嵌套括号
        if '(' in line and ')' in line:
            start = line.find('(')
            if start != -1:
                # 找到匹配的右括号，处理嵌套括号
                paren_count = 0
                end = start
                for i in range(start, len(line)):
                    if line[i] == '(':
                        paren_count += 1
                    elif line[i] == ')':
                        paren_count -= 1
                        if paren_count == 0:
                            end = i
                            break
                
                if end > start:
                    return line[start+1:end]
        return ""
    
    def _extract_block_statements(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取块语句（处理大括号），正确处理控制结构"""
        block_statements = []
        consumed_lines = 0
        brace_count = 0
        found_opening_brace = False
        
        #logger.debug(f"Extracting block from {len(statements)} statements: {[s.strip() for s in statements[:3]]}")
        
        for i, line in enumerate(statements):
            stripped = line.strip()
            
            # 计算大括号
            brace_count += line.count('{') - line.count('}')
            
            if stripped == '{':
                found_opening_brace = True
                consumed_lines += 1
                #logger.debug(f"Found opening brace at line {i}")
                continue
            elif stripped == '}' and brace_count == 0 and found_opening_brace:
                consumed_lines += 1
                #logger.debug(f"Found closing brace at line {i}, ending block")
                break
            elif found_opening_brace and brace_count > 0:
                block_statements.append(line)
                consumed_lines += 1
                #logger.debug(f"Added block statement: {stripped}")
            elif not found_opening_brace and i == 0:
                # 检查第一行是否是控制结构（如for循环头）
                if (stripped.startswith('for ') or stripped.startswith('while ') or 
                    stripped.startswith('if ') or stripped.startswith('switch ')):
                    # 这是控制结构，需要提取整个结构
                    #logger.debug(f"Found control structure: {stripped}")
                    return self._extract_control_structure_block(statements)
                else:
                    # 真正的单行语句
                    block_statements.append(line)
                    consumed_lines += 1
                    #logger.debug(f"Single statement block: {stripped}")
                    break
        
        #logger.debug(f"Extracted {len(block_statements)} statements, consumed {consumed_lines} lines")
        return block_statements, consumed_lines
    
    def _extract_control_structure_block(self, statements: List[str]) -> Tuple[List[str], int]:
        """提取控制结构块（如for循环的整体）"""
        #logger.debug(f"Extracting control structure from {len(statements)} statements")
        
        control_header = statements[0].strip()
        #logger.debug(f"Control header: {control_header}")
        
        # 如果控制结构头包含开大括号，需要找到对应的闭大括号
        if '{' in control_header:
            brace_count = control_header.count('{') - control_header.count('}')
            consumed_lines = 1
            structure_statements = [statements[0]]  # 包含头部
            
            # 继续提取直到大括号平衡
            i = 1
            while i < len(statements) and brace_count > 0:
                line = statements[i]
                stripped = line.strip()
                
                if not stripped:
                    i += 1
                    consumed_lines += 1
                    continue
                
                brace_count += line.count('{') - line.count('}')
                structure_statements.append(line)
                consumed_lines += 1
                
                if brace_count == 0:
                    #logger.debug(f"Control structure closed at line {i}")
                    break
                
                i += 1
            
            #logger.debug(f"Extracted control structure with {len(structure_statements)} statements")
            return structure_statements, consumed_lines
        else:
            # 控制结构头没有大括号，只返回头部
            return [statements[0]], 1
    
    def _extract_java_method_calls(self, code: str) -> List[str]:
        """提取Java代码中的方法调用"""
        method_calls = []
        
        # 匹配方法调用模式 methodName(...)
        pattern = r'(\w+)\s*\('
        matches = re.findall(pattern, code)
        
        for match in matches:
            # 排除Java关键字和常见非方法名
            if (match in self.all_methods and 
                match not in self.java_keywords and
                match not in ['System', 'out', 'println', 'print', 'length']):
                method_calls.append(match)
        
        return list(set(method_calls))  # 去重
    
    def _add_connection(self, from_block: int, to_block: int, connection_type: str):
        """添加块之间的连接"""
        # 检查是否已经存在相同的连接，避免重复
        for existing_conn in self.connections:
            if (existing_conn['from'] == from_block and 
                existing_conn['to'] == to_block and 
                existing_conn['type'] == connection_type):
                return  # 连接已存在，不重复添加
        
        self.connections.append({
            'from': from_block,
            'to': to_block,
            'type': connection_type
        })
    
    def _connect_sequential_blocks(self, block_ids: List[int]):
        """建立顺序块之间的连接"""
        for i in range(len(block_ids) - 1):
            current_block = self.blocks[block_ids[i]]
            next_block = self.blocks[block_ids[i + 1]]
            
            # 跳过控制结构块和不应该有顺序连接的块
            if (current_block['type'] not in ['return', 'break', 'continue', 'throw'] and
                not current_block.get('is_control_structure', False)):
                #logger.debug(f"Adding sequential connection: {block_ids[i]} -> {block_ids[i + 1]}")
                self._add_connection(block_ids[i], block_ids[i + 1], 'sequential')
    
    def _add_java_control_structure_connections(self):
        """添加Java控制结构的额外连接"""
        # 处理if语句的condition_false连接
        self._add_if_condition_false_connections()
        
        # 处理循环的condition_false连接
        self._add_loop_condition_false_connections()
        
        # 添加循环的loop_back连接
        self._add_java_loop_back_connections()
        
        # 处理break语句的跳出连接
        for block in self.blocks:
            if block['type'] == 'break' and 'break_target' in block:
                # 找到循环外的下一个语句
                loop_info = block['break_target']
                exit_target = self._find_loop_exit_target(loop_info)
                if exit_target is not None:
                    self._add_connection(block['id'], exit_target, 'break_exit')
        
        # 处理方法调用连接
        self._add_java_method_call_connections()
        
        # 移除与loop_back连接冲突的sequential连接
        self._remove_conflicting_sequential_connections()
    
    def _remove_conflicting_sequential_connections(self):
        """移除与loop_back连接冲突的sequential连接"""
        # 找到所有有loop_back连接的块
        blocks_with_loop_back = set()
        for conn in self.connections:
            if conn['type'] == 'loop_back':
                blocks_with_loop_back.add(conn['from'])
        
        # 移除这些块的sequential连接
        connections_to_remove = []
        for i, conn in enumerate(self.connections):
            if (conn['type'] == 'sequential' and 
                conn['from'] in blocks_with_loop_back):
                #logger.debug(f"🗑️ Removing conflicting sequential connection: {conn['from']} -> {conn['to']} (block has loop_back)")
                connections_to_remove.append(i)
        
        # 从后往前删除，避免索引问题
        for i in reversed(connections_to_remove):
            del self.connections[i]
        
        # if connections_to_remove:
            #logger.info(f"🗑️ Removed {len(connections_to_remove)} conflicting sequential connections")
    
    def _add_java_loop_back_connections(self):
        """添加Java循环的loop_back连接"""
        for block in self.blocks:
            if block['type'] in ['for_statement', 'while_statement'] and block.get('is_control_structure'):
                loop_block_id = block['id']
                body_blocks = block.get('body_blocks', [])
                
                if body_blocks:
                    # 找到循环体中的最后执行块
                    last_blocks = self._find_java_loop_last_blocks(loop_block_id, body_blocks)
                    
                    # 为每个最后执行块添加loop_back连接
                    for last_block_id in last_blocks:
                        last_block = self.blocks[last_block_id]
                        # 只有非跳转语句才添加loop_back
                        if last_block['type'] not in ['return', 'break', 'continue', 'throw']:
                            self._add_connection(last_block_id, loop_block_id, 'loop_back')
    
    def _find_java_loop_last_blocks(self, loop_block_id: int, body_blocks: List[int]) -> List[int]:
        """找到Java循环体中的最后执行块"""
        if not body_blocks:
            return []
        
        # 获取所有循环块
        all_loop_blocks = self._get_all_loop_blocks(loop_block_id, body_blocks, self.blocks[loop_block_id]['method'])
        
        last_blocks = []
        
        # 找到没有后续连接到循环内其他块的块
        for block_id in all_loop_blocks:
            has_internal_connection = False
            
            # 检查是否有连接到循环内其他块
            for conn in self.connections:
                if (conn['from'] == block_id and 
                    conn['to'] in all_loop_blocks and
                    conn['type'] not in ['loop_back']):
                    has_internal_connection = True
                    break
            
            # 如果没有内部连接，可能是最后执行块
            if not has_internal_connection:
                block = self.blocks[block_id]
                # 排除控制结构头部（它们不是执行块的终点）
                if block['type'] not in ['for_statement', 'while_statement', 'if_statement']:
                    last_blocks.append(block_id)
        
        return last_blocks
    
    def _add_if_condition_false_connections(self):
        """添加if语句的condition_false连接"""
        for block in self.blocks:
            # 只处理if语句
            if block['type'] == 'if_statement' and block.get('is_control_structure'):
                condition = block.get('condition', '')
                then_blocks = block.get('then_blocks', [])
                
                #logger.debug(f"Processing if block {block['id']}: type={block['type']}, condition='{condition}', then_blocks={then_blocks}")
                
                # 找到if语句后的下一个块（condition_false目标）
                false_target = self._find_if_false_target(block['id'], then_blocks)
                if false_target is not None:
                    #logger.debug(f"Adding condition_false connection: {block['id']} -> {false_target}")
                    self._add_connection(block['id'], false_target, f'condition_false:{condition}')
    
    def _add_loop_condition_false_connections(self):
        """添加循环的condition_false连接"""
        for block in self.blocks:
            if block['type'] in ['for_statement', 'while_statement'] and block.get('is_control_structure'):
                condition = block.get('condition', '')
                body_blocks = block.get('body_blocks', [])
                
                #logger.info(f"🔄 Processing loop block {block['id']} ({block['type']}) with body_blocks: {body_blocks}")
                
                # 检查现有连接
                existing_true_conns = [conn for conn in self.connections if conn['from'] == block['id'] and conn['type'].startswith('condition_true:')]
                existing_false_conns = [conn for conn in self.connections if conn['from'] == block['id'] and conn['type'].startswith('condition_false:')]
                #logger.info(f"📋 Before removal - condition_true connections: {len(existing_true_conns)}, condition_false connections: {len(existing_false_conns)}")
                
                # 移除任何错误的condition_false连接（指向循环体内的）
                self._remove_wrong_loop_connections(block['id'], body_blocks)
                
                # 再次检查连接
                remaining_true_conns = [conn for conn in self.connections if conn['from'] == block['id'] and conn['type'].startswith('condition_true:')]
                remaining_false_conns = [conn for conn in self.connections if conn['from'] == block['id'] and conn['type'].startswith('condition_false:')]
                #logger.info(f"📋 After removal - condition_true connections: {len(remaining_true_conns)}, condition_false connections: {len(remaining_false_conns)}")
                
                # 找到循环后的下一个块（condition_false目标）
                false_target = self._find_loop_false_target(block['id'], body_blocks)
                if false_target is not None:
                    #logger.info(f"🎯 Adding condition_false connection: {block['id']} -> {false_target} (condition: {condition})")
                    self._add_connection(block['id'], false_target, f'condition_false:{condition}')
    
    def _remove_wrong_loop_connections(self, loop_block_id: int, body_blocks: List[int]):
        """移除循环块的错误连接"""
        # 移除condition_false指向循环体内的错误连接
        wrong_connections = []
        for i, conn in enumerate(self.connections):
            if (conn['from'] == loop_block_id and 
                conn['type'].startswith('condition_false:') and
                conn['to'] in body_blocks):
                #logger.info(f"🚫 Found wrong condition_false connection to remove: {conn}")
                wrong_connections.append(i)
        
        # 从后往前删除，避免索引问题
        for i in reversed(wrong_connections):
            #logger.info(f"🗑️ Removing wrong connection at index {i}: {self.connections[i]}")
            del self.connections[i]
    
    def _find_if_false_target(self, if_block_id: int, then_blocks: List[int]) -> Optional[int]:
        """找到if语句condition_false的目标块（参考Python CFG builder思路）"""
        if_block = self.blocks[if_block_id]
        method_name = if_block['method']
        
        # 首先查找紧接着的else分支
        else_block = self._find_corresponding_else_block(if_block_id, then_blocks)
        if else_block is not None:
            return else_block
        
        # 检查if语句是否在循环体中
        parent_loop = self._find_parent_loop_for_if(if_block_id)
        if parent_loop is not None:
            #logger.info(f"🔄 If block {if_block_id} is inside loop block {parent_loop}")
            
            # 特殊情况：检查是否是循环体的第一个语句（即循环体直接以if开始）
            parent_loop_block = self.blocks[parent_loop]
            body_blocks = parent_loop_block.get('body_blocks', [])
            
            if body_blocks and body_blocks[0] == if_block_id:
                # 这是循环体的第一个if语句
                #logger.info(f"🎯 If block {if_block_id} is first statement in loop body")
                
                # 对于循环体第一个if语句，如果没有else分支，直接loop back到循环头
                # 这是最符合Java语义的处理方式
                #logger.info(f"🔄 First if in loop body without else, loop back: {if_block_id} -> {parent_loop}")
                return parent_loop
            else:
                # 不是第一个语句，使用原来的逻辑
                next_sibling = self._find_next_sibling_in_loop_body(if_block_id, parent_loop)
                if next_sibling is not None:
                    #logger.info(f"🎯 Found next sibling in loop: {if_block_id} -> {next_sibling}")
                    return next_sibling
                else:
                    # 没有同级下一个语句，loop back到循环头
                    #logger.info(f"🔄 No next sibling, loop back to parent loop: {if_block_id} -> {parent_loop}")
                    return parent_loop
        
        # 不在循环中，使用原来的逻辑
        for block in self.blocks:
            if (block['id'] > if_block_id and 
                block['method'] == method_name and
                block['id'] not in then_blocks):
                return block['id']
        
        return None
    
    def _find_true_sibling_after_if(self, if_block_id: int, parent_loop_id: int, then_blocks: List[int]) -> Optional[int]:
        """查找if语句后真正的同级语句（不在then分支内）"""
        parent_loop_block = self.blocks[parent_loop_id]
        body_blocks = parent_loop_block.get('body_blocks', [])
        
        # 收集所有可能属于if语句的嵌套块
        all_nested_blocks = set(then_blocks)
        
        # 从if语句开始，查找所有可能属于该if语句的块
        # 假设从if_block_id到下一个控制结构之间的所有块都属于当前if
        for i, block_id in enumerate(body_blocks):
            if block_id == if_block_id:
                # 从if语句之后开始检查
                for j in range(i + 1, len(body_blocks)):
                    candidate_id = body_blocks[j]
                    candidate_block = self.blocks[candidate_id]
                    
                    # 如果遇到另一个控制结构，说明找到了真正的同级语句
                    if candidate_block['type'] in ['if_statement', 'for_statement', 'while_statement']:
                        #logger.info(f"✅ Found control structure sibling: {candidate_id}")
                        return candidate_id
                    
                    # 如果遇到简单语句且不在then_blocks中，可能是同级语句
                    if candidate_id not in all_nested_blocks:
                        #logger.info(f"✅ Found simple statement sibling: {candidate_id}")
                        return candidate_id
                
                break
        
        #logger.info(f"❌ No true sibling found after if {if_block_id}")
        return None
    
    def _find_parent_loop_for_if(self, if_block_id: int) -> Optional[int]:
        """找到包含if语句的父循环块"""
        if_block = self.blocks[if_block_id]
        method_name = if_block['method']
        
        # 查找同一方法中的所有循环块
        for block in self.blocks:
            if (block['method'] == method_name and 
                block['type'] in ['for_statement', 'while_statement'] and
                block['id'] < if_block_id):
                
                # 检查if块是否在这个循环的body_blocks中
                body_blocks = block.get('body_blocks', [])
                if if_block_id in body_blocks:
                    #logger.debug(f"Found parent loop {block['id']} for if block {if_block_id}")
                    return block['id']
        
        return None
    
    def _find_next_sibling_in_loop_body(self, if_block_id: int, parent_loop_id: int) -> Optional[int]:
        """在循环体中找到if语句的下一个真正同级语句"""
        parent_loop = self.blocks[parent_loop_id]
        body_blocks = parent_loop.get('body_blocks', [])
        
        # 获取if语句的then分支
        if_block = self.blocks[if_block_id]
        then_blocks = if_block.get('then_blocks', [])
        
        #logger.debug(f"🔍 Looking for sibling of if block {if_block_id}, then_blocks: {then_blocks}")
        
        # 在body_blocks中找到if_block的位置
        try:
            if_index = body_blocks.index(if_block_id)
        except ValueError:
            return None
        
        # 计算需要跳过的所有嵌套块（包括then分支内的所有块）
        nested_blocks = set(then_blocks)
        
        # 递归找到then分支内所有嵌套的if语句的then分支
        self._collect_all_nested_blocks(then_blocks, nested_blocks)
        
        #logger.debug(f"🔍 All nested blocks to skip: {sorted(nested_blocks)}")
        
        # 从if_index+1开始查找，跳过所有嵌套块
        for i in range(if_index + 1, len(body_blocks)):
            candidate_block_id = body_blocks[i]
            
            # 如果这个块不在嵌套块中，说明它是真正的同级语句
            if candidate_block_id not in nested_blocks:
                #logger.debug(f"✅ Found true sibling block {candidate_block_id} for if block {if_block_id}")
                return candidate_block_id
        
        # 没有找到同级下一个语句
        #logger.debug(f"❌ No true sibling found for if block {if_block_id} in loop {parent_loop_id}")
        return None
    
    def _collect_all_nested_blocks(self, block_ids: List[int], nested_blocks: set):
        """递归收集所有嵌套块"""
        for block_id in block_ids:
            if block_id < len(self.blocks):
                block = self.blocks[block_id]
                if block['type'] == 'if_statement':
                    # 如果是if语句，递归收集其then分支
                    then_blocks = block.get('then_blocks', [])
                    for then_block_id in then_blocks:
                        nested_blocks.add(then_block_id)
                    self._collect_all_nested_blocks(then_blocks, nested_blocks)
    
    def _find_corresponding_else_block(self, if_block_id: int, then_blocks: List[int]) -> Optional[int]:
        """找到if语句对应的else分支的第一个块"""
        if_block = self.blocks[if_block_id]
        method_name = if_block['method']
        
        # 启发式方法：对于if语句后跟for循环的情况
        # 如果then_blocks只有一个for循环，且后面紧接着另一个for循环
        # 那么第二个for循环很可能是else分支
        if (then_blocks and len(then_blocks) == 1):
            first_then_block = self.blocks[then_blocks[0]]
            if first_then_block['type'] == 'for_statement':
                # 查找if分支之后可能的else分支
                # 跳过if分支内的所有块，找到下一个可能的control structure
                for block in self.blocks:
                    if (block['id'] > if_block_id and 
                        block['method'] == method_name and
                        block['id'] not in then_blocks):
                        # 如果找到另一个for循环，很可能是else分支
                        if block['type'] == 'for_statement':
                            return block['id']
                        # 如果找到return语句，说明没有else分支
                        elif block['type'] == 'return':
                            break
        
        return None
    
    def _find_loop_false_target(self, loop_block_id: int, body_blocks: List[int]) -> Optional[int]:
        """找到循环condition_false的目标块"""
        loop_block = self.blocks[loop_block_id]
        method_name = loop_block['method']
        
        # 找到循环的同级下一步：
        # 1. 找到所有属于循环的块（包括嵌套的控制结构）
        all_loop_blocks = self._get_all_loop_blocks(loop_block_id, body_blocks, method_name)
        
        # 2. 找到循环后第一个不属于循环的块
        for block in self.blocks:
            if (block['id'] > loop_block_id and 
                block['method'] == method_name and
                block['id'] not in all_loop_blocks):
                return block['id']
        
        return None
    
    def _get_all_loop_blocks(self, loop_block_id: int, body_blocks: List[int], method_name: str) -> List[int]:
        """获取循环的所有块（包括循环体内的嵌套结构）"""
        if not body_blocks:
            return []
        
        all_loop_blocks = list(body_blocks)
        min_body = min(body_blocks)
        max_body = max(body_blocks)
        
        # 查找body_blocks之间的所有块（可能是嵌套的控制结构）
        for block in self.blocks:
            if (block['id'] > min_body and 
                block['id'] < max_body and
                block['method'] == method_name and
                block['id'] not in all_loop_blocks):
                all_loop_blocks.append(block['id'])
        
        return sorted(all_loop_blocks)
    
    def _find_loop_exit_target(self, loop_info: Dict) -> Optional[int]:
        """找到循环的退出目标"""
        # 找到循环后的第一个块
        loop_header_id = loop_info.get('header_id')
        if loop_header_id is None:
            return None
        
        loop_block = self.blocks[loop_header_id]
        loop_method = loop_block['method']
        
        # 找到同一方法内循环后的第一个非循环相关块
        for block in self.blocks:
            if (block['method'] == loop_method and 
                block['id'] > loop_header_id and
                block['type'] not in ['break', 'continue'] and
                not self._is_block_in_loop(block, loop_info)):
                return block['id']
        
        return None
    
    def _is_block_in_loop(self, block: Dict, loop_info: Dict) -> bool:
        """检查块是否在指定循环内"""
        # 简化判断：通过块ID范围判断
        loop_header_id = loop_info.get('header_id')
        if loop_header_id is None:
            return False
        
        # 如果块的方法与循环头的方法相同，且ID在合理范围内
        return (block['method'] == self.blocks[loop_header_id]['method'] and
                block['id'] > loop_header_id and
                block['id'] < loop_header_id + 50)  # 假设循环不会超过50个块
    
    def _add_java_method_call_connections(self):
        """添加Java方法调用连接"""
        for block in self.blocks:
            if block.get('method_calls'):
                for method_call in block['method_calls']:
                    if method_call in self.all_methods:
                        # 找到被调用方法的第一个块
                        method_first_block = self._find_method_first_block(method_call)
                        if method_first_block is not None:
                            self._add_connection(block['id'], method_first_block, 'method_call')
                        
                        # 找到被调用方法的返回块
                        method_return_blocks = self._find_method_return_blocks(method_call)
                        for return_block in method_return_blocks:
                            self._add_connection(return_block, block['id'], 'method_return')
    
    def _find_method_first_block(self, method_name: str) -> Optional[int]:
        """找到方法的第一个块"""
        for block in self.blocks:
            if block['method'] == method_name:
                return block['id']
        return None
    
    def _find_method_return_blocks(self, method_name: str) -> List[int]:
        """找到方法的所有返回块"""
        return_blocks = []
        for block in self.blocks:
            if (block['method'] == method_name and 
                block['type'] == 'return'):
                return_blocks.append(block['id'])
        return return_blocks
    
    def _process_method_calls_in_blocks(self, visited_methods: Set[str]):
        """处理所有块中的方法调用"""
        methods_to_process = set()
        for block in self.blocks:
            if block.get('method_calls'):
                for method_call in block['method_calls']:
                    if method_call in self.all_methods and method_call not in visited_methods:
                        methods_to_process.add(method_call)
        
        # 处理每个方法调用
        for method_call in methods_to_process:
            #logger.info(f"发现方法调用: {method_call}")
            self._build_method_cfg(method_call, visited_methods.copy())
    
    def _generate_cfg_text(self) -> str:
        """生成CFG的文本表示"""
        header = f"G describes a control flow graph of Method `{self.method_signature}`\nIn this graph:"
        
        # 找到主方法的第一个执行块作为起点
        entry_block_id = self._find_main_method_entry_block()
        end_block_id = len(self.blocks)
        
        # 专门说明Entry Point和END Block
        entry_info = []
        if entry_block_id is not None:
            entry_block = self.blocks[entry_block_id]
            entry_code = entry_block['code'].replace('\n', '\\n')
            entry_info.append(f"Entry Point: Block {entry_block_id} represents code snippet: {entry_code}.")
        entry_info.append(f"END Block: Block {end_block_id} represents code snippet: END.")
        
        # 生成块描述
        block_descriptions = []
        for block in self.blocks:
            code = block['code'].replace('\n', '\\n')
            block_descriptions.append(f"Block {block['id']} represents code snippet: {code}.")
        
        # 添加统一的END标记
        block_descriptions.append(f"Block {end_block_id} represents code snippet: END.")
        
        # 生成连接描述
        edge_descriptions = []
        sorted_connections = sorted(self.connections, key=lambda x: (x['from'], x['to']))
        
        # 去重处理
        seen_connections = set()
        unique_connections = []
        for conn in sorted_connections:
            conn_key = (conn['from'], conn['to'], conn['type'])
            if conn_key not in seen_connections:
                seen_connections.add(conn_key)
                unique_connections.append(conn)
        
        for conn in unique_connections:
            conn_type = conn['type']
            
            if conn_type == 'sequential':
                edge_descriptions.append(f"Block {conn['from']} unconditional points to Block {conn['to']}.")
            elif conn_type == 'loop_back':
                edge_descriptions.append(f"Block {conn['from']} loop back to Block {conn['to']}.")
            elif conn_type == 'continue':
                edge_descriptions.append(f"Block {conn['from']} continue points to Block {conn['to']}.")
            elif conn_type == 'break_exit':
                edge_descriptions.append(f"Block {conn['from']} break exit points to Block {conn['to']}.")
            elif conn_type == 'method_call':
                edge_descriptions.append(f"Block {conn['from']} method call points to Block {conn['to']}.")
            elif conn_type == 'method_return':
                edge_descriptions.append(f"Block {conn['from']} method return points to Block {conn['to']}.")
            elif conn_type.startswith('condition_true:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('condition_false:'):
                condition = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} not match case \"{condition}\" points to Block {conn['to']}.")
            elif conn_type.startswith('case_match:'):
                case_value = conn_type.split(':', 1)[1]
                edge_descriptions.append(f"Block {conn['from']} case match \"{case_value}\" points to Block {conn['to']}.")
            elif conn_type == 'default_case':
                edge_descriptions.append(f"Block {conn['from']} default case points to Block {conn['to']}.")
            elif conn_type == 'exception':
                edge_descriptions.append(f"Block {conn['from']} exception points to Block {conn['to']}.")
            elif conn_type == 'finally':
                edge_descriptions.append(f"Block {conn['from']} finally points to Block {conn['to']}.")
            else:
                edge_descriptions.append(f"Block {conn['from']} {conn_type} points to Block {conn['to']}.")
        
        # 为主方法的return语句添加到END的连接
        for block in self.blocks:
            if (block['type'] == 'return' and 
                block['method'] == self.target_method):
                edge_descriptions.append(f"Block {block['id']} unconditional points to Block {end_block_id}.")
        
        # 组合所有部分
        body_parts = entry_info + block_descriptions + edge_descriptions
        body = "\n".join(body_parts)
        return f"{header}\n{body}"
    
    def _find_main_method_entry_block(self) -> Optional[int]:
        """找到主方法的第一个执行块（入口点）"""
        for block in self.blocks:
            if block['method'] == self.target_method:
                return block['id']
        return None
    
    def print_features(self):
        """打印CFG特征信息"""
        #logger.info("=================Improved Java Method CFG=================")
        #logger.info(f"目标类: {self.target_class}")
        #logger.info(f"目标方法: {self.target_method}")
        #logger.info(f"方法签名: {self.method_signature}")
        #logger.info(f"所有类: {list(self.all_classes.keys())}")
        #logger.info(f"所有方法: {list(self.all_methods.keys())}")
        #logger.info(f"块数量: {self.block_num}")
        #logger.info(f"连接数量: {len(self.connections)}")
        
        #logger.info("块信息:")
        # for block in self.blocks: 
            #logger.info(f"  Block {block['id']} ({block['type']}): {block['code'][:50]}...")
        
        #logger.info("连接信息:")
        # for conn in self.connections:
            #logger.info(f"  {conn['from']} --{conn['type']}--> {conn['to']}")
        
        #logger.info(f"CFG文本表示:\n{self.cfg_text}")
        #logger.info("=================Improved Java Method CFG=================")


# 测试函数
def test_improved_java_cfg():
    """测试改进的Java CFG构建器"""
    test_code = '''
public class TestClass {
    
    public int helperMethod(int x) {
        if (x > 0) {
            return x * 2;
        } else {
            return x * -1;
        }
    }
    
    public int[] mainMethod(int[] arr) {
        int[] result = new int[arr.length];
        int index = 0;
        
        try {
            for (int i = 0; i < arr.length; i++) {
                if (arr[i] > 0) {
                    continue;
                } else if (arr[i] == 0) {
                    break;
                }
                
                int processed = helperMethod(arr[i]);
                result[index++] = processed;
            }
            
            while (index > 5) {
                index--;
            }
        } catch (Exception e) {
            System.out.println("Error occurred");
            result = new int[0];
        } finally {
            System.out.println("Processing completed");
        }
        
        return result;
    }
}
'''
    
    # 写入测试文件
    test_file = "TestClassImproved.java"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    try:
        # 测试改进的Java CFG构建器
        cfg = JavaCFG(test_file, "mainMethod", "TestClass")
        cfg.print_features()
        
        print(f"\n生成的块数量: {cfg.block_num}")
        print(f"生成的连接数量: {len(cfg.connections)}")
        
    finally:
        # 清理测试文件
        import os
        if os.path.exists(test_file):
            os.remove(test_file)


if __name__ == "__main__":
    test_improved_java_cfg() 