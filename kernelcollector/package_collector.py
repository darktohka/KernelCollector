from bs4 import BeautifulSoup
from . import utils
import json, logging, tempfile, re, shutil, os, uuid, multiprocessing, traceback
import requests

FIND_IMAGE_RM = 'rm -f /lib/modules/$version/.fresh-install'
NEW_FIND_IMAGE_RM = 'rm -rf /lib/modules/$version'
INITRD_IMAGE_RMS = ['rm -f /boot/initrd.img-$version', 'rm -f /var/lib/initramfs-tools/$version']
DEB_CONTENT_TYPE = 'application/x-debian-package'
DAILY_RELEASE_REGEX = re.compile(r'\d{4}-\d{2}-\d{2}')

class PackageCollector(object):

    def __init__(self, logger, architectures, pkg_list):
        self.logger = logger
        self.architectures = architectures
        self.pkg_list = pkg_list
        self.tmp_dir = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        self.current_dir = os.getcwd()
        self.reload_cache()

    def run_all_builds(self):
        # Get all releases and prereleases
        logging.info(f'Current directory is {self.current_dir}')
        logging.info('Checking latest source versions of the kernel...')

        stable_name, stable_link, mainline_name, mainline_link = self.get_kernel_releases()
        logging.info(f'Current source release: v{stable_name}')
        logging.info(f'Current source release candidate: v{mainline_name}')

        logging.info('Checking latest binary versions of the kernel...')

        releases, prereleases = self.get_ubuntu_releases()
        daily_releases = self.get_daily_releases()
        downloaded = False

        # Delete the temporary folder
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

        # Redownload stable build if necessary
        release, downloadable_release = self.find_downloadable_files(releases, 'linux-current')
        prerelease, downloadable_prerelease = self.find_downloadable_files(prereleases, 'linux-beta')
        daily_release, downloadable_daily_release = self.find_downloadable_files(daily_releases, 'linux-devel')
        downloadable_stable = self.find_downloadable_sources('linux-stable', stable_name, stable_link)
        downloadable_mainline = self.find_downloadable_sources('linux-mainline', mainline_name, mainline_link)

        downloadable = downloadable_release + downloadable_prerelease + downloadable_daily_release + downloadable_stable + downloadable_mainline

        logging.info(f'Current binary release: {release}')
        logging.info(f'Current binary release candidate: {prerelease}')
        logging.info(f'Current binary daily build: {daily_release}')

        self.logger.send_all()

        # Update cache and publish repository
        if not downloadable:
            return

        # Create the temporary folder
        os.makedirs(self.tmp_dir)

        # Schedule pool
        downloadable_queue = utils.split_list(downloadable, multiprocessing.cpu_count())
        downloadable_queue = [q for q in downloadable_queue if q]
        worker_count = len(downloadable_queue)

        # Create and run the pool
        pool = multiprocessing.Pool(processes=worker_count)
        file_caches = pool.map(self.download_files_worker, list(enumerate(downloadable_queue)))
        downloaded = any(file_caches)

        # Update the global file cache from the multiprocessing pool
        for cache in file_caches:
            self.file_cache.update(cache)

        # Update the cache if necessary
        if downloaded:
            self.update_cache()
            self.publish_repository()

        # Remove temporary folder
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def get_kernel_releases(self):
        with requests.get('https://kernel.org') as site:
            data = site.content

        soup = BeautifulSoup(data, 'html.parser')
        table_rows = soup.find_all('tr')
        mainline_entry = next((row for row in table_rows if 'mainline' in row.text), None)
        stable_entry = next((row for row in table_rows if 'stable' in row.text), None)

        if mainline_entry is None:
            mainline_entry = stable_entry
        if stable_entry is None:
            stable_entry = mainline_entry
        if mainline_entry is None or stable_entry is None:
            raise Exception('No mainline or stable entries found.')

        # Extract the version and download link for mainline
        mainline_version = mainline_entry.find('strong').text
        mainline_download_link = mainline_entry.find('a', {'title': 'Download complete tarball'})['href']

        # Extract the version and download link for stable
        stable_version = stable_entry.find('strong').text
        stable_download_link = stable_entry.find('a', {'title': 'Download complete tarball'})['href']

        return stable_version, stable_download_link, mainline_version, mainline_download_link

    def get_ubuntu_releases(self):
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
        prereleases.sort(key=lambda x: utils.release_to_tuple(x), reverse=True)
        releases.sort(key=lambda x: utils.release_to_tuple(x), reverse=True)

        # At the end of every release candidate cycle, a new kernel version is released.
        # Upgrade the prerelease branch if there is no newer prerelease than the current release.
        if utils.release_to_tuple(releases[-1])[0:2] >= utils.release_to_tuple(prereleases[-1])[0:2]:
            prereleases.append(releases[-1])

        return releases, prereleases

    def get_daily_releases(self):
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

    def get_files(self, release_link, release_type):
        with requests.get(f'https://kernel.ubuntu.com/~kernel-ppa/mainline/{release_link}') as site:
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

            found_current = False

            # There are three kinds of packages: images, modules and headers;
            # and they can be either generic, low latency or snapdragon (the processor)
            # The only package that doesn't have a sub type is headers-all, which is archless
            for type in ('image', 'modules', 'headers'):
                if f'-{type}-' not in text:
                    continue

                for sub_type in ('lpae', 'lowlatency', 'snapdragon', 'generic'):
                    if not f'-{sub_type}' in text:
                        continue

                    file_type = f'{release_type}-{type}-{sub_type}-{arch}'

                    if file_type in files:
                        files[file_type].append(text)
                    else:
                        files[file_type] = [text]

                    found_current = True
                    break

            if (not found_current) and '-headers-' in text:
                files[f'{release_type}-headers-all'] = [text]

        return files

    def download_and_repack_source(self, release_link, release_name, release_type):
        archive_name = f'{release_type}.tar.xz'
        temp_filename = os.path.join(self.tmp_dir, archive_name)
        archive_filename = os.path.join(self.pkg_list.src_folder, archive_name)

        logging.info(f'Downloading source for release {release_name} from {release_link}')

        try:
            utils.download_file_to_xz(release_link, temp_filename)
        except:
            self.logger.add(f'Could not download {archive_name} from {release_link}!', alert=True)
            self.logger.add(traceback.format_exc(), pre=True)
            self.logger.send_all()
            return

        if not os.path.exists(self.pkg_list.src_folder):
            os.makedirs(self.pkg_list.src_folder)

        if os.path.exists(archive_filename):
            os.remove(archive_filename)

        shutil.copyfile(temp_filename, archive_filename)
        os.remove(temp_filename)

    def download_and_repack(self, release_link, release_name, release_type, pkg_name, filenames):
        if release_type in ('linux-stable', 'linux-mainline'):
            return self.download_and_repack_source(release_link, release_name, release_type)

        deb_filename = os.path.join(self.tmp_dir, pkg_name + '.deb')
        extract_folder = os.path.join(self.tmp_dir, uuid.uuid4().hex)
        control_filename = os.path.join(extract_folder, 'DEBIAN', 'control')
        postrm_filename = os.path.join(extract_folder, 'DEBIAN', 'postrm')

        # Create a temporary folder for the repackaging
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)

        os.makedirs(extract_folder)

        # Kernel versions such as 5.0 have to be adjusted to 5.0.0
        if release_type != 'linux-devel':
            names = release_name.split('-')
            release = list(utils.release_to_tuple(names[0]))

            while len(release) < 3:
                release.append(0)

            names[0] = '.'.join([str(num) for num in release])
            release_name = '-'.join(names)

        for i, filename in enumerate(filenames):
            primary_file = i == 0
            link = f'https://kernel.ubuntu.com/~kernel-ppa/mainline/{release_link}/{filename}'

            # Download the .deb
            logging.info(f'Downloading package {pkg_name} (release v{release_name}) from {link}')

            try:
                utils.download_file(link, deb_filename, DEB_CONTENT_TYPE)
            except:
                self.logger.add(f'Could not download {os.path.basename(deb_filename)} from {link}!', alert=True)
                self.logger.add(traceback.format_exc(), pre=True)
                self.logger.send_all()
                return

            # Extract the .deb file
            extract_flag = '-R' if primary_file else '-x'
            result = utils.run_process(['dpkg-deb', extract_flag, deb_filename, extract_folder])

            if result.failed:
                self.logger.add(f'Could not extract {os.path.basename(deb_filename)} (error code {result.exit_code})!', alert=True)
                self.logger.add(result.get_output(), pre=True)
                self.logger.send_all()
                return

            if not primary_file:
                # Auxiliary packages: unpack metadata into a secondary folder
                aux_extract_folder = os.path.join(self.tmp_dir, uuid.uuid4().hex)

                if os.path.exists(aux_extract_folder):
                    shutil.rmtree(aux_extract_folder)

                os.makedirs(aux_extract_folder)
                result = utils.run_process(['dpkg-deb', '-e', deb_filename, aux_extract_folder])

                if result.failed:
                    self.logger.add(f'Could not extract metadata {os.path.basename(deb_filename)} (error code {result.exit_code})!', alert=True)
                    self.logger.add(result.get_output(), pre=True)
                    self.logger.send_all()
                    return

                # Merge md5sum metadata
                with open(os.path.join(extract_folder, 'DEBIAN', 'md5sums'), 'a+') as target_hash_file:
                    with open(os.path.join(aux_extract_folder, 'md5sums'), 'r') as source_hash_file:
                        target_hash_file.write(source_hash_file.read())

                # Remove secondary folder
                if os.path.exists(aux_extract_folder):
                    shutil.rmtree(aux_extract_folder)

            os.remove(deb_filename)

        if not os.path.exists(control_filename):
            self.logger.add(f'No control file for {pkg_name}...', alert=True)
            self.logger.send_all()
            return

        # Rewrite the control file
        with open(control_filename, 'r') as f:
            control_lines = f.read().replace('\r', '').split('\n')

        # We have to rewrite the package name, the version
        # We will also remove all linux based dependencies
        # In addition to this, we will replace conflicts with our own conflicts
        # For example, generic packages will conflict with lowlatency and snapdragon packages
        for i, line in enumerate(control_lines):
            if line.startswith('Package:'):
                control_lines[i] = f'Package: {pkg_name}'
            elif line.startswith('Version:'):
                control_lines[i] = f'Version: {release_name}'
            elif line.startswith('Depends: '):
                dependencies = [dep for dep in line[len('Depends: '):].split(', ') if not dep.startswith('linux-')]

                # libssl3 and newer libc6 is not available on Debian.
                dependencies = [dep for dep in dependencies if not dep.startswith('libc6') and not dep.startswith('libssl3')]

                # initramfs depends on the logsave script, which is not installed by default.
                # Without the logsave script, the system will not boot.
                if 'image' in pkg_name:
                    if 'logsave' not in dependencies:
                        dependencies.append('logsave')

                depends = ', '.join(dependencies)
                control_lines[i] = f'Depends: {depends}'
            elif line.startswith('Conflicts'):
                orig_conflicts = ['generic', 'lowlatency', 'snapdragon']
                conflicts = [conflict for conflict in orig_conflicts if conflict not in pkg_name]

                for conflict in conflicts:
                    orig_conflicts.remove(conflict)

                my_type = orig_conflicts[0]
                conflicts = [pkg_name.replace(my_type, conflict) for conflict in conflicts]
                conflicts = ', '.join(conflicts)
                control_lines[i] = f'Conflicts: {conflicts}'

        with open(control_filename, 'w') as f:
            f.write('\n'.join(control_lines))

        # The Ubuntu kernel images do not remove initrd.img in the postrm script.
        # Remove the initrd.img right before the fresh-install file is removed.
        if os.path.exists(postrm_filename):
            with open(postrm_filename, 'r') as f:
                postrm_lines = f.read().replace('\r', '').split('\n')

            if FIND_IMAGE_RM in postrm_lines:
                index = postrm_lines.index(FIND_IMAGE_RM)
                postrm_lines[index] = NEW_FIND_IMAGE_RM

                for rm_line in INITRD_IMAGE_RMS:
                    postrm_lines.insert(index, rm_line)

                with open(postrm_filename, 'w') as f:
                    f.write('\n'.join(postrm_lines))

        # Repack the .deb file
        result = utils.run_process(['dpkg-deb', '-Zgzip', '-b', extract_folder, deb_filename])

        if result.failed:
            self.logger.add(f'Could not pack {os.path.basename(deb_filename)} (error code {result.exit_code})!', alert=True)
            self.logger.add(result.get_output(), pre=True)
            self.logger.send_all()
            return

        self.pkg_list.add_deb_to_pool(deb_filename)

        # Remove the temporary extract folder
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)

    def download_files_worker(self, worker_args):
        i, files = worker_args

        logging.info(f'Starting worker number {i + 1} with {len(files)} packages to download...')
        file_cache = {}

        # Go through all files
        for release_link, release_name, release_type, pkg_name, filenames in files:
            # Download and repack
            self.download_and_repack(release_link, release_name, release_type, pkg_name, filenames)
            file_cache[pkg_name] = filenames

        logging.info(f'Worker number {i + 1} has finished.')
        return file_cache

    def find_downloadable_sources(self, release_type, release_version, release_link):
        filenames = [release_link]

        if self.file_cache.get(release_type, None) == filenames:
            return []

        return [[release_link, f'v{release_version}', release_type, release_type, filenames]]

    def find_downloadable_files(self, releases, release_type):
        # Download the file list for this release
        required_types = ['image', 'modules', 'headers']

        for release in releases:
            if DAILY_RELEASE_REGEX.match(release):
                release_link = f'daily/{release}'
                release_name = release
            else:
                release_link = release
                release_name = release[1:]

            files = self.get_files(release_link, release_type)
            current_types = []

            for pkg_name in files.keys():
                type = pkg_name.split('-')

                if len(type) < 3:
                    continue

                type = type[2]

                if type in required_types and type not in current_types:
                    current_types.append(type)

            if len(current_types) == len(required_types):
                # Found all files necessary
                break

            self.logger.add(f'Release is not yet ready: {release_type}')

        filtered_files = []

        for pkg_name, filenames in files.items():
            # Check our cache
            if self.file_cache.get(pkg_name, None) == filenames:
                continue

            filtered_files.append([release_link, release_name, release_type, pkg_name, filenames])

        return release, filtered_files

    def reload_cache(self):
        # Reload the cache.
        # We use the cache to avoid redownloading and repackaging files that we've already processed
        try:
            with open('cache.json', 'r') as file:
                self.cache = json.load(file)
        except:
            self.cache = {}

        self.file_cache = self.cache.get('files', {})

    def update_cache(self):
        # Save the cache to disk.
        self.cache['files'] = self.file_cache

        with open('cache.json', 'w') as file:
            json.dump(self.cache, file, sort_keys=True, indent=4, separators=(',', ': '))

    def publish_repository(self):
        # If temporary directory doesn't exist, nothing matters
        self.pkg_list.save_all_distributions(['l', 'custom'])
        self.pkg_list.send_embedded_report()
