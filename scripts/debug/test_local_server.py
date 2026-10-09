import subprocess
import time
import urllib.request

proc = subprocess.Popen('npx next start -p 3333', shell=True, cwd=r'c:\Users\REDX420\Desktop\recetagenial', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(6)

try:
    req = urllib.request.Request('http://127.0.0.1:3333/test-slug-123456')
    try:
        resp = urllib.request.urlopen(req)
        print('HTTP Status:', resp.status)
        print('Headers:', dict(resp.headers))
    except urllib.error.HTTPError as e:
        print('HTTP Error Code:', e.code)
        print('Headers:', dict(e.headers))
except Exception as e:
    print('Request error:', e)
finally:
    subprocess.run('taskkill /F /T /PID ' + str(proc.pid), shell=True, capture_output=True)
