import urllib.request, json
req = urllib.request.Request('https://api.github.com/repos/gorkem-b/RealityCheck/actions/runs/29638636244/jobs')
req.add_header('User-Agent', 'python')
response = urllib.request.urlopen(req)
jobs = json.loads(response.read())['jobs']
job = jobs[0]
print('Job:', job['name'])
for s in job['steps']:
    print('-', s['name'], ':', s['conclusion'])
