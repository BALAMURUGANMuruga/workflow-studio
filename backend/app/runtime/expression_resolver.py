# Resolve workflow expressions such as ${inputs.orderNo} against the current execution context.
# Use Python's regular-expression library to identify workflow references.
import re
# Any allows inputs and outputs to retain their original runtime types.
from typing import Any
# Capture the path between the reference delimiters for lookup.
TOKEN=re.compile(r"\$\{([^{}]+)\}")
# Input: a workflow value and a context mapping. Output: a resolved value of the appropriate type.
def resolve(value: Any, context: dict):
    # Resolve each dictionary value recursively and preserve its key.
    if isinstance(value,dict): return {k:resolve(v,context) for k,v in value.items()}
    # Resolve each list element recursively and preserve its position.
    if isinstance(value,list): return [resolve(v,context) for v in value]
    # Pass numbers, booleans, and null through directly.
    if not isinstance(value,str): return value
    # Read one dotted reference from the execution context.
    def lookup(path):
        # Start traversal at the top-level inputs, variables, config, or steps mapping.
        current=context
        # Split the path into fields and optional list indexes.
        for part in path.strip().split("."):
            # Read the named field, returning None for a missing key.
            if isinstance(current,dict): current=current.get(part)
            # Accept a numeric index only when it is inside the list.
            elif isinstance(current,list) and part.isdigit() and int(part)<len(current): current=current[int(part)]
            # Stop at an unsupported traversal or an invalid index.
            else: return None
        # Return the final object exactly as stored.
        return current
    # Check whether the entire input string consists of one reference.
    exact=TOKEN.fullmatch(value)
    # Preserve the referenced value's type for a standalone reference.
    if exact: return lookup(exact.group(1))
    # Interpolate references embedded in longer strings and substitute empty text for missing values.
    return TOKEN.sub(lambda m: str(lookup(m.group(1)) if lookup(m.group(1)) is not None else ""),value)
