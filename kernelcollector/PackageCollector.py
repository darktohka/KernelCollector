from bs4 import BeautifulSoup
from . import Utils
import json, logging, tempfile, re, shutil, os, time, uuid, multiprocessing
import requests

FIND_IMAGE_RM = 'rm -f /lib/modules/$version/.fresh-install'
NEW_FIND_IMAGE_RM = 'rm -rf /lib/modules/$version'
INITRD_IMAGE_RMS = ['rm -f /boot/initrd.img-$version', 'rm -f /var/lib/initramfs-tools/$version']
DEB_CONTENT_TYPE = 'application/x-debian-package'
DAILY_RELEASE_REGEX = re.compile(r'\d{4}-\d{2}-\d{2}')

class PackageCollector(object):

    def __init__(self, logger, architectures, pkgList):
        self.logger = logger
        self.architectures = architectures
        self.pkgList = pkgList
        self.tmpDir = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        self.currentDir = os.getcwd()
        self.reloadCache()

    def runAllBuilds(self):
        # Get all releases and prereleases
        logging.info(f'Current directory is {self.currentDir}')
        logging.info('Checking latest versions of the kernel...')
        releases, prereleases = self.getAllReleases()

        # At the end of every release candidate cycle, a new kernel version is released.
        # Upgrade the prerelease branch if there is no newer prerelease than the current release.
        if Utils.releaseToTuple(releases[-1][1:])[0:2] >= Utils.releaseToTuple(prereleases[-1][1:])[0:2]:
            prereleases.append(releases[-1])

        dailyReleases = self.getDailyReleases()
        downloaded = False

        # Delete the temporary folder
        if os.path.exists(self.tmpDir):
            shutil.rmtree(self.tmpDir)

        # Redownload stable build if necessary
        release, downloadable_release = self.findDownloadableFiles(releases, 'linux-current')
        prerelease, downloadable_prerelease = self.findDownloadableFiles(prereleases, 'linux-beta')
        dailyRelease, downloadable_daily_release = self.findDownloadableFiles(dailyReleases, 'linux-devel')

        downloadable = downloadable_release + downloadable_prerelease + downloadable_daily_release

        logging.info(f'Current release: {release}')
        logging.info(f'Current release candidate: {prerelease}')
        logging.info(f'Current daily build: {dailyRelease}')
        self.logger.send_all()

        # Update cache and publish repository
        if not downloadable:
            return

        # Create the temporary folder
        os.makedirs(self.tmpDir)

        # Schedule pool
        downloadable_queue = self.splitList(downloadable, multiprocessing.cpu_count())
        downloadable_queue = [q for q in downloadable_queue if q]
        worker_count = len(downloadable_queue)

        # Create and run the pool
        pool = multiprocessing.Pool(processes=worker_count)
        file_caches = pool.map(self.downloadFilesWorker, list(enumerate(downloadable_queue)))
        downloaded = any(file_caches)

        # Update the global file cache from the multiprocessing pool
        for file_cache in file_caches:
            self.fileCache.update(file_cache)

        # Update the cache if necessary
        if downloaded:
            self.updateCache()
            self.publishRepository()

        # Remove temporary folder
        if os.path.exists(self.tmpDir):
            shutil.rmtree(self.tmpDir)

    def splitList(self, a, n):
        k, m = divmod(len(a), n)
        return (a[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n))

    def getAllReleases(self):
        # We use the Ubuntu kernel mainline as the build source.
        # This method will return a list of releases and prereleases, sorted in ascending order.
        with requests.get('https://kernel.ubuntu.com/~kernel-ppa/mainline') as site:
            data = site.content

        soup = BeautifulSoup(data, 'html.parser')
        prereleases = []
        releases = []

        for row in soup.findAll('tr'):
            tds = row.findAll('td')

            if len(tds) != 5:
                continue

            a = tds[1].find('a')

            if not a:
                continue

            name = a.text
            prerelease = '-rc' in name

            # Some Ubuntu specific kernel versions will have to be skipped, for example 2.6.32-xenial
            if len(name) < 2 or name[0] != 'v' or (not name[1].isdigit()) or ('-' in name and not prerelease) or (name.count('-') > 1):
                continue

            # Since we're reading links, they might have trailing slashes
            name = name.rstrip('/')

            if prerelease:
                prereleases.append(name)
            else:
                releases.append(name)

        # Sort the releases in descending order
        prereleases.sort(key=lambda x: Utils.releaseToTuple(x[1:]), reverse=True)
        releases.sort(key=lambda x: Utils.releaseToTuple(x[1:]), reverse=True)

        return releases, prereleases

    def getDailyReleases(self):
        # We have to find the newest daily release version
        with requests.get('https://kernel.ubuntu.com/~kernel-ppa/mainline/daily') as site:
            data = site.content

        soup = BeautifulSoup(data, 'html.parser')
        versions = []

        for row in soup.findAll('tr'):
            tds = row.findAll('td')

            if len(tds) != 5:
                continue

            a = tds[1].find('a')

            # The link encapsulated inside the <a> tag and the text of the tag will match for daily releases
            if a and a['href'] == a.text:
                version = a.text.rstrip('/')

                if version != 'current':
                    versions.append(version)

        return sorted(versions, reverse=True)

    def getFiles(self, releaseLink, releaseType):
        with requests.get(f'https://kernel.ubuntu.com/~kernel-ppa/mainline/{releaseLink}') as site:
            data = site.content

        files = {}
        soup = BeautifulSoup(data, 'html.parser')
        arch = None

        for a in soup.findAll('a'):
            text = a.text

            # We have multiple options.
            # If we've reached a build log, that means that we've switched to a new architecture.
            # If we've reached MainlineBuilds, then we're done with all architectures.
            # If we have a chosen architecture and the file is a .deb package, then it has to be in
            # our list of architectures and it must not be an lpae-based build (we don't package those)
            if text.endswith('/log'):
                arch = text[:text.find('/log')]
                continue
            elif text == 'Name':
                break
            elif not text.endswith('.deb') or not arch:
                continue
            elif arch not in self.architectures:
                continue
            elif '-lpae' in text:
                continue

            foundCurrent = False

            # There are three kinds of packages: images, modules and headers;
            # and they can be either generic, low latency or snapdragon (the processor)
            # The only package that doesn't have a sub type is headers-all, which is archless
            for type in ('image', 'modules', 'headers'):
                if f'-{type}-' not in text:
                    continue

                for subType in ('lpae', 'lowlatency', 'snapdragon', 'generic'):
                    if not f'-{subType}' in text:
                        continue

                    fileType = f'{releaseType}-{type}-{subType}-{arch}'

                    if fileType in files:
                        files[fileType].append(text)
                    else:
                        files[fileType] = [text]

                    foundCurrent = True
                    break

            if (not foundCurrent) and '-headers-' in text:
                files[f'{releaseType}-headers-all'] = [text]

        return files

    def downloadAndRepack(self, releaseLink, releaseName, releaseType, pkgName, filenames):
        debFilename = os.path.join(self.tmpDir, pkgName + '.deb')
        extractFolder = os.path.join(self.tmpDir, uuid.uuid4().hex)
        controlFilename = os.path.join(extractFolder, 'DEBIAN', 'control')
        postrmFilename = os.path.join(extractFolder, 'DEBIAN', 'postrm')

        # Create a temporary folder for the repackaging
        if os.path.exists(extractFolder):
            shutil.rmtree(extractFolder)

        os.makedirs(extractFolder)

        # Kernel versions such as 5.0 have to be adjusted to 5.0.0
        if releaseType != 'linux-devel':
            names = releaseName.split('-')
            release = list(Utils.releaseToTuple(names[0]))

            while len(release) < 3:
                release.append(0)

            names[0] = '.'.join([str(num) for num in release])
            releaseName = '-'.join(names)

        for i, filename in enumerate(filenames):
            primaryFile = i == 0
            link = f'https://kernel.ubuntu.com/~kernel-ppa/mainline/{releaseLink}/{filename}'

            # Download the .deb
            logging.info(f'Downloading package {pkgName} (release v{releaseName}) from {link}')

            try:
                Utils.downloadFile(link, debFilename, DEB_CONTENT_TYPE)
            except:
                self.logger.add(f'Could not download {os.path.basename(debFilename)} from {link}!', alert=True)
                self.logger.add(traceback.print_exc(), pre=True)
                self.logger.send_all()
                return

            # Extract the .deb file
            extractFlag = '-R' if primaryFile else '-x'
            result = Utils.run_process(['dpkg-deb', extractFlag, debFilename, extractFolder])

            if result.failed:
                self.logger.add(f'Could not extract {os.path.basename(debFilename)} (error code {result.exit_code})!', alert=True)
                self.logger.add(result.get_output(), pre=True)
                self.logger.send_all()
                return

            if not primaryFile:
                # Auxiliary packages: unpack metadata into a secondary folder
                secondaryExtractFolder = os.path.join(self.tmpDir, uuid.uuid4().hex)

                if os.path.exists(secondaryExtractFolder):
                    shutil.rmtree(secondaryExtractFolder)

                os.makedirs(secondaryExtractFolder)
                result = Utils.run_process(['dpkg-deb', '-e', debFilename, secondaryExtractFolder])

                if result.failed:
                    self.logger.add(f'Could not extract metadata {os.path.basename(debFilename)} (error code {result.exit_code})!', alert=True)
                    self.logger.add(result.get_output(), pre=True)
                    self.logger.send_all()
                    return

                # Merge md5sum metadata
                with open(os.path.join(extractFolder, 'DEBIAN', 'md5sums'), 'a+') as targetHashFile:
                    with open(os.path.join(secondaryExtractFolder, 'md5sums'), 'r') as sourceHashFile:
                        targetHashFile.write(sourceHashFile.read())

                # Remove secondary folder
                if os.path.exists(secondaryExtractFolder):
                    shutil.rmtree(secondaryExtractFolder)

            os.remove(debFilename)

        if not os.path.exists(controlFilename):
            self.logger.add(f'No control file for {pkgName}...', alert=True)
            self.logger.send_all()
            return

        # Rewrite the control file
        with open(controlFilename, 'r') as f:
            controlLines = f.read().replace('\r', '').split('\n')

        # We have to rewrite the package name, the version
        # We will also remove all linux based dependencies
        # In addition to this, we will replace conflicts with our own conflicts
        # For example, generic packages will conflict with lowlatency and snapdragon packages
        for i, line in enumerate(controlLines):
            if line.startswith('Package:'):
                controlLines[i] = f'Package: {pkgName}'
            elif line.startswith('Version:'):
                controlLines[i] = f'Version: {releaseName}'
            elif line.startswith('Depends: '):
                dependencies = [dep for dep in line[len('Depends: '):].split(', ') if not dep.startswith('linux-')]

                # libssl3 and newer libc6 is not available on Debian.
                dependencies = [dep for dep in dependencies if not dep.startswith('libc6') and not dep.startswith('libssl3')]

                # initramfs depends on the logsave script, which is not installed by default.
                # Without the logsave script, the system will not boot.
                if 'image' in pkgName:
                    if 'logsave' not in dependencies:
                        dependencies.append('logsave')

                controlLines[i] = 'Depends: {0}'.format(', '.join(dependencies))
            elif line.startswith('Conflicts'):
                origConflicts = ['generic', 'lowlatency', 'snapdragon']
                conflicts = [conflict for conflict in origConflicts if conflict not in pkgName]

                for conflict in conflicts:
                    origConflicts.remove(conflict)

                myType = origConflicts[0]
                conflicts = [pkgName.replace(myType, conflict) for conflict in conflicts]
                controlLines[i] = 'Conflicts: {0}'.format(', '.join(conflicts))

        with open(controlFilename, 'w') as f:
            f.write('\n'.join(controlLines))

        # The Ubuntu kernel images do not remove initrd.img in the postrm script.
        # Remove the initrd.img right before the fresh-install file is removed.
        if os.path.exists(postrmFilename):
            with open(postrmFilename, 'r') as f:
                postrmLines = f.read().replace('\r', '').split('\n')

            if FIND_IMAGE_RM in postrmLines:
                index = postrmLines.index(FIND_IMAGE_RM)
                postrmLines[index] = NEW_FIND_IMAGE_RM

                for rmLine in INITRD_IMAGE_RMS:
                    postrmLines.insert(index, rmLine)

                with open(postrmFilename, 'w') as f:
                    f.write('\n'.join(postrmLines))

        # Repack the .deb file
        result = Utils.run_process(['dpkg-deb', '-Zgzip', '-b', extractFolder, debFilename])

        if result.failed:
            self.logger.add(f'Could not pack {os.path.basename(debFilename)} (error code {result.exit_code})!', alert=True)
            self.logger.add(result.get_output(), pre=True)
            self.logger.send_all()
            return

        self.pkgList.addDebToPool(debFilename)

        # Remove the temporary extract folder
        if os.path.exists(extractFolder):
            shutil.rmtree(extractFolder)

    def downloadFilesWorker(self, worker_args):
        i, files = worker_args

        logging.info(f'Starting worker number {i + 1} with {len(files)} packages to download...')
        file_cache = {}

        # Go through all files
        for releaseLink, releaseName, releaseType, pkgName, filenames in files:
            # Download and repack
            self.downloadAndRepack(releaseLink, releaseName, releaseType, pkgName, filenames)
            file_cache[pkgName] = filenames

        logging.info(f'Worker number {i + 1} has finished.')
        return file_cache

    def findDownloadableFiles(self, releases, releaseType):
        # Download the file list for this release
        requiredTypes = ['image', 'modules', 'headers']

        for release in releases:
            if DAILY_RELEASE_REGEX.match(release):
                releaseLink = f'daily/{release}'
                releaseName = release
            else:
                releaseLink = release
                releaseName = release[:1]

            files = self.getFiles(releaseLink, releaseType)
            currentTypes = []

            for pkgName in files.keys():
                type = pkgName.split('-')

                if len(type) < 3:
                    continue

                type = type[2]

                if type in requiredTypes and type not in currentTypes:
                    currentTypes.append(type)

            if len(currentTypes) == len(requiredTypes):
                # Found all files necessary
                break

            self.logger.add(f'Release is not yet ready: {releaseType}')

        filtered_files = []

        for pkgName, filenames in files.items():
            # Check our cache
            if self.fileCache.get(pkgName, None) == filenames:
                continue

            filtered_files.append([releaseLink, releaseName, releaseType, pkgName, filenames])

        return release, filtered_files

    def reloadCache(self):
        # Reload the cache.
        # We use the cache to avoid redownloading and repackaging files that we've already processed
        try:
            with open('cache.json', 'r') as file:
                self.cache = json.load(file)
        except:
            self.cache = {}

        self.fileCache = self.cache.get('files', {})

    def updateCache(self):
        # Save the cache to disk.
        self.cache['files'] = self.fileCache

        with open('cache.json', 'w') as file:
            json.dump(self.cache, file, sort_keys=True, indent=4, separators=(',', ': '))

    def publishRepository(self):
        # If temporary directory doesn't exist, nothing matters
        self.pkgList.saveAllDistributions(['l', 'custom'])
        self.pkgList.sendEmbeddedReport()
