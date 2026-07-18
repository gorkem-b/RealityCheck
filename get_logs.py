import urllib.request, json
req = urllib.request.Request('https://api.github.com/repos/gorkem-b/RealityCheck/actions/runs/29638636244/jobs')
req.add_header('User-Agent', 'python')
response = urllib.request.urlopen(req)
jobs = json.loads(response.read())['jobs']
job = jobs[0]
job_id = job['id']
print('Job ID:', job_id)
log_req = urllib.request.Request(f'https://api.github.com/repos/gorkem-b/RealityCheck/actions/jobs/{job_id}/logs')
log_req.add_header('User-Agent', 'python')
try:
    log_response = urllib.request.urlopen(log_req)
    print(log_response.read().decode('utf-8'))
except Exception as e:
    print('Failed to get logs:', e)
