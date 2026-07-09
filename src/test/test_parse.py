import ast
import traceback
code = r"""print(f"  {item['name']} {'[DIR]' if item['is_dir'] else '(' + str(item['size']) + ' bytes)'}")"""
print("Code:", code)
import sys
print(sys.version)
try:
    ast.parse(code)
    print("Success")
except Exception as e:
    traceback.print_exc()
