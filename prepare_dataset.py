import json
import random

# Load both files
with open('data/final_fq17-generated_prompt_query_annotated.json') as f:
    data = json.load(f)

with open('data/sparql_complexities.json') as f:
    cx_list = json.load(f)

# Build complexity lookup
cx = {item['id']: item['complexity'] for item in cx_list}

# Merge into clean rows
rows = []
for i in range(len(data['query'])):
    key = str(i)
    rows.append({
        'id':          key,
        'instruction': data['instructions'][key][0],
        'query':       data['query'][key],
        'annotated':   data['query_templated'][key],
        'complexity':  cx.get(key, 'unknown'),
    })

# Split: 75% train, 5% val, 20% test — stratified by complexity
random.seed(42)
train, val, test = [], [], []

for complexity in ['simple', 'medium', 'complex']:
    subset = [r for r in rows if r['complexity'] == complexity]
    random.shuffle(subset)
    n_test = int(len(subset) * 0.20)
    n_val  = int(len(subset) * 0.05)
    test.extend(subset[:n_test])
    val.extend(subset[n_test:n_test + n_val])
    train.extend(subset[n_test + n_val:])

# Save splits
for name, split in [('train', train), ('val', val), ('test', test)]:
    with open(name + '.json', 'w') as f:
        json.dump(split, f, indent=2)

# Print stats
print('Split    Simple   Medium  Complex    Total')
print('-' * 44)
for name, split in [('train', train), ('val', val), ('test', test)]:
    s = sum(1 for r in split if r['complexity'] == 'simple')
    m = sum(1 for r in split if r['complexity'] == 'medium')
    c = sum(1 for r in split if r['complexity'] == 'complex')
    print(name.ljust(8), str(s).rjust(6), str(m).rjust(8), str(c).rjust(8), str(len(split)).rjust(8))

print()
print('Example row from train:')
print('  Instruction:', train[0]['instruction'])
print('  Complexity: ', train[0]['complexity'])
print('  SPARQL:     ', train[0]['query'][:120])
