# Take a workflow value and a text command. Python re and lxml apply supported XML and JSON transformations.
"""Apply supported prompt commands to a workflow value."""

import re
from typing import Any

from lxml import etree

from .xml_xpath import parse_sample

# Restrict the root names matched by the command to this character set.
NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
# Match supported natural-language commands and capture the old and new root names.
RENAME = re.compile(rf"^(?:get\s+[^.!?]{{1,80}}?\s+(?:and\s+|then\s+)?)?(?:rename|change)\s+(?:the\s+)?root(?:\s+(?:key|element|tag|name))?\s+"
                    rf"""(?:from\s+)?[`'"]?({NAME})[`'"]?\s+to\s+[`'"]?({NAME})[`'"]?\s*[.!]?$""", re.I)
# Match an extract command and capture its dotted JSON path.
EXTRACT = re.compile(r"""^(?:get|extract|select)\s+(?:the\s+)?(?:field\s+)?[`'"]?"""
                     r"""([@\w-]+(?:\.[@\w-]+)*)[`'"]?\s*[.!]?$""", re.I)


def transform_with_prompt(data: Any, prompt: str) -> Any:
    """Rename a root or select a JSON path while preserving the selected value."""
    # Validate the command type before applying string operations.
    if not isinstance(prompt, str):
        raise ValueError("Enter a transformation prompt.")
    # Remove surrounding whitespace before matching.
    instruction = prompt.strip()
    # Try to match a root rename first.
    rename = RENAME.search(instruction)
    if rename:
        # Read the two captured root names.
        old, new = rename.groups()
        # Treat a string rename input as XML.
        if isinstance(data, str):
            # Parse the XML string into an lxml element tree.
            root = parse_sample(data)
            # Read the XML local name and optional namespace.
            name = etree.QName(root)
            # Reject the operation if the input has a different root.
            if name.localname != old:
                # Report a missing field or invalid index to the workflow executor.
                raise ValueError(f"Expected XML root {old}; found {name.localname}.")
            # Change the tag and preserve the namespace when present.
            root.tag = f"{{{name.namespace}}}{new}" if name.namespace else new
            # Serialize the renamed tree back to a string for the next step.
            return etree.tostring(root, encoding="unicode")
        # For JSON, require a dictionary with exactly the requested root key.
        if not isinstance(data, dict) or len(data) != 1 or old not in data:
            raise ValueError(f"Expected a single JSON root key named {old}. Select the parsed API response as the data source.")
        # Return the same nested data inside the renamed root.
        return {new: data[old]}

    # Try a dotted field extraction if the command did not request a rename.
    extract = EXTRACT.fullmatch(instruction)
    if extract:
        # Begin traversal at the input value.
        value = data
        # Retrieve the matched dotted path.
        path = extract.group(1)
        # Walk one segment at a time.
        for key in path.split("."):
            # Read the next named item from a dictionary.
            if isinstance(value, dict) and key in value:
                value = value[key]
            # Allow a bounded numeric segment to address a list item.
            elif isinstance(value, list) and key.isdigit() and len(key) <= 9 and int(key) < len(value):
                value = value[int(key)]
            else:
                # Report a missing field or invalid index to the workflow executor.
                raise ValueError(f"The JSON field {path} could not be found.")
        # Return the value found at the end of the path.
        return value

    # Reject unsupported commands with examples of accepted syntax.
    raise ValueError("Use a supported prompt such as 'Rename the root from Order to OrderResult' or 'Extract field Order.@Status'.")
