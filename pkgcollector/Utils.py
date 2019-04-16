import requests, re

def prereleaseToTuple(name):
    return tuple(int(x) for x in re.split('\\-rc|\\.', name, 0))

def releaseToTuple(name):
    return tuple(int(x) for x in name.split('.'))

def downloadFile(link, destination):
    with requests.get(link, stream=True) as r:
        r.raise_for_status()

        with open(destination, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

            f.flush()
