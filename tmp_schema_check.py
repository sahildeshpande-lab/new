from app.database import get_schema_summary
schema = get_schema_summary()
print('database:', schema.get('database'))
print('tables:', len(schema.get('tables', {})))
for t in sorted(schema.get('tables', {}))[:50]:
    cols = [c['name'] for c in schema['tables'][t]['columns']]
    print(t, cols[:10], '... total', len(cols))
