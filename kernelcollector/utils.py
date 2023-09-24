import hashlib, subprocess, re, zlib, lzma
import requests

class ContentTypeException(Exception):
    pass

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

def remove_version_prefix(version):
    return re.sub(r'[^0-9\.\-rc]', '', version)

def release_to_tuple(name):
    name = remove_version_prefix(name)
    return tuple(int(x) for x in re.split('\\-rc|\\.', name, 0))

def stream_gzip_decompress(stream):
    dec = zlib.decompressobj(32 + zlib.MAX_WBITS)  # offset 32 to skip the header

    for chunk in stream:
        rv = dec.decompress(chunk)

        if rv:
            yield rv

    if dec.unused_data:
        yield dec.flush()

def stream_xz_compress(stream):
    enc = lzma.LZMACompressor(lzma.FORMAT_XZ)

    for chunk in stream:
        rv = enc.compress(chunk)

        if rv:
            yield rv

    yield enc.flush()

def download_file(link, destination, expected_content_type):
    with requests.get(link, stream=True) as r:
        r.raise_for_status()

        content_type = r.headers.get('content-type', 'unset')

        if content_type != expected_content_type:
            raise ContentTypeException(f'Expected content type {expected_content_type} but received {content_type}.')

        with open(destination, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1048576):
                if chunk:
                    f.write(chunk)

            f.flush()

def download_file_to_xz(link, destination):
    with requests.get(link, stream=True) as r:
        r.raise_for_status()

        content_type = r.headers.get('content-type', 'unset')

        with open(destination, 'wb') as f:
            iterator = r.iter_content(chunk_size=1048576)

            if 'application/x-gzip' in content_type:
                iterator = stream_gzip_decompress(iterator)

            if 'application/x-xz' not in content_type:
                iterator = stream_xz_compress(iterator)

            with open(destination, 'wb') as f:
                for chunk in iterator:
                    if chunk:
                        f.write(chunk)

                f.flush()

def get_all_hashes(filename):
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

def split_list(a, n):
    k, m = divmod(len(a), n)
    return (a[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n))
