import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(__file__))

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def normalize(s):
    return re.sub(r'[^a-z0-9]', '', s or '').lower()

def to_snake(s):
    if not s:
        return s
    # replace non-alnum with underscore, convert CamelCase/space to snake_case
    s = re.sub(r'(.)([A-Z][a-z]+)', r"\1_\2", s)
    s = re.sub(r'([a-z0-9])([A-Z])', r"\1_\2", s)
    s = re.sub(r'[^0-9a-zA-Z]+', '_', s)
    s = s.strip('_').lower()
    s = re.sub(r'__+', '_', s)
    return s

def build_training_keys(training):
    keys = set()
    definitions = training.get('definitions', {}) or {}
    for f in training.get('fields', []):
        keys.add(f.get('fieldKey'))
    # include definition object fields (for arrays)
    def_map = {}
    for name, obj in definitions.items():
        def_keys = [f.get('fieldKey') for f in obj.get('fields', [])]
        def_map[name] = def_keys
    return keys, def_map

SYNONYMS = {
    'billingaddress': 'CustomerAddress',
    'invoicenumber': 'InvoiceId',
    'total': 'InvoiceTotal',
    'amount': 'InvoiceTotal'
}

def find_training_match(field_key, training_keys):
    if field_key in training_keys:
        return field_key
    n = normalize(field_key)
    # direct normalized match
    for k in training_keys:
        if normalize(k) == n:
            return k
    # synonym table
    if n in SYNONYMS:
        s = SYNONYMS[n]
        if s in training_keys:
            return s
    # look for short name matches
    for k in training_keys:
        if normalize(k).endswith(n) or n.endswith(normalize(k)):
            return k
    return None

def generate_for(doc_type, overwrite=True):
    base = os.path.join(ROOT, 'procurement_automation')
    training_path = os.path.join(base, 'training-data', 'procurement-dataset.v0', doc_type, 'fields.json')
    schema_path = os.path.join(base, 'backend', 'processing', 'field_schemas', f'{doc_type}.json')
    out_dir = os.path.join(base, 'backend', 'processing', 'jmespath')
    out_path = os.path.join(out_dir, f'{doc_type}.jmespath.json')

    training = None
    if os.path.exists(training_path):
        training = load_json(training_path)
    else:
        print(f"training fields not found for {doc_type}, aborting")
        return False

    training_keys, def_map = build_training_keys(training)

    out = {
        'schemaVersion': 1,
        'documentType': doc_type,
        'fields': []
    }

    if os.path.exists(schema_path):
        schema = load_json(schema_path)
        # Use schema as source of systemKeys, try to match training for paths
        for f in schema.get('fields', []):
            if f.get('fieldType') == 'array':
                entry = {
                    'systemKey': f.get('systemKey'),
                    'array': True,
                    'path': None,
                    'required': False,
                    'itemSchema': []
                }
                match = find_training_match(f.get('fieldKey'), training_keys)
                if match:
                    entry['path'] = f"documents[0].fields.{match}"
                else:
                    entry['needs_review'] = True
                for it in f.get('itemFields', []):
                    item_path = it.get('fieldKey')
                    entry['itemSchema'].append({
                        'systemKey': it.get('systemKey'),
                        'path': item_path if item_path else None,
                        'required': False,
                        'expectedType': it.get('fieldType')
                    })
                out['fields'].append(entry)
                continue

            fk = f.get('fieldKey')
            sys = f.get('systemKey')
            expected = f.get('fieldType')
            matched = find_training_match(fk, training_keys)
            entry = {
                'systemKey': sys,
                'path': None,
                'required': False,
                'expectedType': expected
            }
            if matched:
                entry['path'] = f"documents[0].fields.{matched}"
                fallbacks = []
                if fk == 'CustomerAddress' and 'BillingAddress' in training_keys:
                    fallbacks.append('documents[0].fields.BillingAddress')
                if fk == 'customer_address' and 'BillingAddress' in training_keys:
                    fallbacks.append('documents[0].fields.BillingAddress')
                if fallbacks:
                    entry['fallbackPaths'] = fallbacks
            else:
                entry['needs_review'] = True
            out['fields'].append(entry)
    else:
        # Schema missing: derive systemKey names from training field keys
        for f in training.get('fields', []):
            fk = f.get('fieldKey')
            ftype = f.get('fieldType')
            if ftype == 'array':
                # derive item type from definitions if present
                item_type = f.get('itemType')
                item_fields = []
                if item_type and item_type in def_map:
                    for it in def_map[item_type]:
                        item_fields.append({
                            'systemKey': to_snake(it),
                            'path': it,
                            'required': False,
                            'expectedType': None
                        })
                entry = {
                    'systemKey': to_snake(fk),
                    'array': True,
                    'path': f"documents[0].fields.{fk}",
                    'required': False,
                    'itemSchema': item_fields
                }
                out['fields'].append(entry)
                continue

            entry = {
                'systemKey': to_snake(fk),
                'path': f"documents[0].fields.{fk}",
                'required': False,
                'expectedType': ftype
            }
            out['fields'].append(entry)

    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(out_path):
        if not overwrite:
            print(f"{out_path} exists and overwrite disabled")
            return False
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"wrote {out_path}")
    return True

def main():
    p = argparse.ArgumentParser()
    p.add_argument('doc_types', nargs='*', default=['invoice','purchase-order','goods-receipt-note'])
    p.add_argument('--no-overwrite', action='store_true')
    args = p.parse_args()

    for d in args.doc_types:
        ok = generate_for(d, overwrite=not args.no_overwrite)
        if not ok:
            print(f"failed for {d}")

if __name__ == '__main__':
    main()
