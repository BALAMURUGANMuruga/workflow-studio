# Parse input XML and evaluate XPath with lxml. Return matched values to the caller.
"""Parse uploaded XML and evaluate generated XPath expressions."""

from lxml import etree


# Parse an XML string into an lxml root with external entities and network access disabled.
def parse_sample(xml: str):
    # Reject empty, oversized, or non-text samples before passing data to lxml.
    if not isinstance(xml, str) or not xml.strip() or len(xml) > 200_000:
        raise ValueError("Provide XML between 1 and 200,000 characters.")
    # Read UTF-8, disable external resolution, and skip maintaining an XML ID index.
    parser = etree.XMLParser(encoding="UTF-8", resolve_entities=False, load_dtd=False,
                             no_network=True, collect_ids=False)
    try:
        # Convert the submitted text to bytes and parse the entire document.
        root = etree.fromstring(xml.strip().encode("utf-8"), parser)
    except (etree.XMLSyntaxError, UnicodeError) as exc:
        raise ValueError("The sample must be a well-formed XML document.") from exc
    # Reject documents declaring a DTD even if their XML is otherwise well formed.
    if root.getroottree().docinfo.doctype:
        raise ValueError("XML document type declarations are unsupported.")
    return root


# Accept XML, an XPath expression, and namespace prefixes. Return a dictionary of matches.
def extract_xpath_values(xml: str, xpath: str, namespaces: dict[str, str]) -> dict:
    # Validate XML first, then evaluate the XPath with the caller's namespace mappings.
    values = evaluate_xpath(parse_sample(xml), xpath, namespaces)
    # Report the full match count while limiting the returned values to the first 100.
    return {"matches": len(values), "values": values[:100], "truncated": len(values) > 100}


# Apply the expression to a parsed root and convert matching elements or scalar results into strings.
def evaluate_xpath(root, xpath: str, namespaces: dict[str, str]) -> list[str]:
    try:
        # Use plain strings for XPath text and attribute results.
        matches = root.xpath(xpath, namespaces=namespaces, smart_strings=False)
    except etree.XPathError as exc:
        raise ValueError("The XPath could not be evaluated.") from exc
    # Reject a scalar XPath expression such as count(...) because callers expect a selection.
    if not isinstance(matches, list):
        raise ValueError("The XPath must select XML nodes.")
    # Flatten descendant text for elements. Convert selected attributes and text nodes to strings.
    return ["".join(value.itertext()) if isinstance(value, etree._Element) else str(value) for value in matches]
