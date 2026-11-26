// Build available result-field mappings from workflow outputs.
import type { DesignerStep, DesignerXmlTemplate } from '../../services/workflow-api.service';

export interface ResultField {
  dataPath: string;
  source: string;
  key: string;
  xmlPath?: string;
}

export function resultFieldId(field: ResultField): string {
  return field.xmlPath ? `${field.source}|${field.xmlPath}` : field.source;
}

export function apiResultFields(steps: DesignerStep[], templates: DesignerXmlTemplate[]): ResultField[] {
  const fields = new Map<string, ResultField>();
  const add = (field: ResultField) => fields.set(resultFieldId(field), field);
  for (const step of steps) {
    const saved = step['saveAs'] ?? step['output'];
    if (step.type !== 'api' || step['action'] || typeof saved !== 'string' || !saved) continue;
    const variable = `variables.${saved}`;
    const mapping = step['responseMapping'] as { strategy?: string; fields?: { target?: string }[] } | undefined;
    const mapped = mapping?.strategy === 'field' && step['responseFormat'] !== 'xml';
    if (mapped) {
      for (const item of mapping?.fields ?? []) {
        if (item.target) add({ dataPath: variable, source: `${variable}.${item.target}`, key: item.target });
      }
      if (step['responseFormat'] === 'json') continue;
    }
    const response = (step['xml_templates'] as { response?: { file?: string; id?: string; xml?: string } } | undefined)?.response;
    if (!response) continue;
    const xml = response.xml ?? templates.find(template => template.kind === 'response'
      && template.file === (response.file || 'output-templates') && (!response.id || template.id === response.id))?.xml;
    if (!xml || /<!DOCTYPE/i.test(xml)) continue;
    const root = new DOMParser().parseFromString(xml, 'application/xml').documentElement;
    if (!root || root.localName === 'parsererror') continue;
    const source = step['responseFormat'] === 'xml' ? `${variable}.xml`
      : mapped ? `${variable}.raw.xml` : `${variable}.response`;
    const raw = step['responseFormat'] === 'xml' || mapped;
    const visit = (node: Element, path: string) => {
      for (const attr of Array.from(node.attributes)) {
        if (attr.namespaceURI === 'http://www.w3.org/2000/xmlns/') continue;
        const xmlPath = `${path}.@${attr.name}`;
        const key = attr.localName.replace(/^[A-Z]+(?=[A-Z][a-z]|$)|^[A-Z]/, prefix => prefix.toLowerCase());
        add(raw ? { dataPath: source, source, xmlPath, key } : { dataPath: source, source: `${source}.${xmlPath}`, key });
      }
      const children = Array.from(node.children);
      for (const child of children) {
        const siblings = children.filter(item => item.tagName === child.tagName);
        const suffix = !raw && siblings.length > 1 ? `.${siblings.indexOf(child)}` : '';
        visit(child, `${path}.${child.tagName}${suffix}`);
      }
    };
    visit(root, root.tagName);
  }
  return [...fields.values()];
}
