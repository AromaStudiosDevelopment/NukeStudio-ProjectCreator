import re

# The text exactly as you provided (handling the formatting artifacts)
text = """'Auto Comments.\\n'
 ' | | |\\n'
 '|--|--|\\n'
 '| location: | '
 '`\\\\192.168.150.179\\share2\\storage2\\Projects\\TVC\\Sameh_20250914\\footage\\copy001\\shots\\copy001_sh0040\\pl01\\v001` '   
 '|'"""


text2 = """|  |  |
|--|--|
| Workfile| `//192.168.150.179/VFX_Projects/2025/TVC/Sameh_20250914/gizmo_v02.nk` |
| Location | `\\192.168.150.179\share2\footage\A001_C037_0921FG_001.mov` |"""
# New Pattern Explanation:
# 1. "location:" -> Find the anchor text
# 2. ".*?"       -> Match any garbage characters (spaces, pipes, quotes, newlines) minimally
# 3. "`"         -> Stop at the opening backtick
# 4. "([^`]+)"   -> CAPTURE everything inside until the next backtick
location_pattern = r"location.*?`([^`]+)`"
Workfile_pattern = r"Workfile.*?`([^`]+)`"

# re.DOTALL allows the "." to skip over new lines if the string is broken up
match = re.search(location_pattern, text2, re.IGNORECASE | re.DOTALL)

if match:
    # simply extracting the string 
    print(f"Extracted: {match.group(1)}")
else:
    print("No match found.")