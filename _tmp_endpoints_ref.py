from pettycash import create_app

app = create_app()
endpoints = []
for r in app.url_map.iter_rules():
    endpoints.append((r.endpoint, str(r.rule), sorted(r.methods) if r.methods else []))

uniq = sorted(set(endpoints), key=lambda x: x[0])
for ep, rule, methods in uniq:
    print(f"{ep}\t{rule}\t{','.join(sorted(set(methods)-{'HEAD','OPTIONS'}))}")
