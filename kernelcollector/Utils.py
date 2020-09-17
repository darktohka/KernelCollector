import hashlib, subprocess, re
import requests

class ProcessOutput(object):

    def __init__(self, lines, exit_code):
        self.lines = lines
        self.exit_code = exit_code

    def get_lines(self):
        return self.lines

    def get_output(self):
        return ''.join(self.lines)

    @property
    def success(self):
        return self.exit_code == 0

    @property
    def failed(self):
        return self.exit_code != 0

def run_process(process):
    if isinstance(process, str):
        process = process.split()

    try:
        process = subprocess.Popen(process, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        return ProcessOutput([], -1)

    lines = []

    with process.stdout:
        for line in iter(process.stdout.readline, b''):
            if line:
                lines.append(line.decode('utf-8'))

    process.wait()
    return ProcessOutput(lines, process.returncode)

def releaseToTuple(name):
    return tuple(int(x) for x in re.split('\\-rc|\\.', name, 0))

def downloadFile(link, destination):
    with requests.get(link, stream=True) as r:
        r.raise_for_status()

        with open(destination, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

            f.flush()

def getAllHashes(filename):
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()

    with open(filename, 'rb') as file:
        while True:
            data = file.read(65536)

            if not data:
                break

            md5.update(data)
            sha1.update(data)
            sha256.update(data)

    return md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()
