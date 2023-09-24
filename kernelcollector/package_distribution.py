from deb_pkg_tools.control import unparse_control_fields
from datetime import datetime
from . import utils
import traceback, logging, gzip, os
import gnupg

gpg = gnupg.GPG()
gpg.encoding = 'utf-8'

class PackageDistribution(object):

    def __init__(self, logger, name, architectures, description):
        self.logger = logger
        self.name = name
        self.architectures = architectures
        self.description = description

    def set_package_list(self, pkg_list):
        self.pkg_list = pkg_list

        if not self.pkg_list:
            return

        self.folder = os.path.join(self.pkg_list.dist_folder, self.name)

        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

    def get_arch_dir(self, arch):
        return os.path.join(self.folder, 'main', f'binary-{arch}')

    def sign_file(self, filename, content, detach=False):
        with open(filename, 'w') as file:
            try:
                file.write(str(gpg.sign(content, detach=detach, keyid=self.pkg_list.gpg_key, passphrase=self.pkg_list.gpg_password)))
            except:
                self.logger.add(f'Could not sign {filename}! Please check your GPG keys!', alert=True)
                self.logger.add(traceback.format_exc(), pre=True)
                self.logger.send_all()

    def save(self, releases):
        main_dir = os.path.join(self.folder, 'main')
        arch_to_packages = {arch: [] for arch in self.architectures}

        logging.info('Writing package list to disk...')

        # Associate our packages with architectures.
        for release in releases:
            full_path, data = release
            arch = data['Architecture'].lower()
            data = unparse_control_fields(data).dump()

            if arch == 'all':
                for arch in self.architectures:
                    arch_to_packages[arch].append(data)
            elif arch in self.architectures:
                arch_to_packages[arch].append(data)

        # Write our package lists for all architectures.
        for arch in self.architectures:
            arch_dir = self.get_arch_dir(arch)

            if not os.path.exists(arch_dir):
                os.makedirs(arch_dir)

            with open(os.path.join(arch_dir, 'Release'), 'w') as file:
                file.write('\n'.join([
                    'Component: main', 'Origin: linux-kernel', 'Label: linux-kernel',
                    f'Architecture: {arch}', f'Description: {self.description}'
                ]))

            packages = '\n'.join(arch_to_packages[arch])

            with open(os.path.join(arch_dir, 'Packages'), 'w') as file:
                file.write(packages)

            with gzip.open(os.path.join(arch_dir, 'Packages.gz'), 'wt') as file:
                file.write(packages)

        # Gather hashes for the architecture package lists.
        md5s = []
        sha1s = []
        sha256s = []

        date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S UTC')

        for root, _, files in os.walk(main_dir):
            for file in files:
                full_path = os.path.join(root, file)
                display_path = full_path[len(self.folder):].lstrip('/')

                md5, sha1, sha256 = utils.get_all_hashes(full_path)
                size = str(os.path.getsize(full_path))
                md5s.append(f' {md5} {size} {display_path}')
                sha1s.append(f' {sha1} {size} {display_path}')
                sha256s.append(f' {sha256} {size} {display_path}')

        # Save the final package list, signing
        archs = ' '.join(self.architectures)
        md5s = '\n'.join(md5s)
        sha1s = '\n'.join(sha1s)
        sha256s = '\n'.join(sha256s)
        release = '\n'.join([
            'Origin: linux-kernel', 'Label: linux-kernel', f'Suite: {self.name}', f'Codename: {self.name}', f'Date: {date}',
            f'Architectures: {archs}', 'Components: main', f'Description: {self.description}',
            f'MD5Sum:\n{md5s}', f'SHA1:\n{sha1s}', f'SHA256:\n{sha256s}'
        ])

        with open(os.path.join(self.folder, 'Release'), 'w') as file:
            file.write(release)

        self.sign_file(os.path.join(self.folder, 'InRelease'), release, detach=False)
        self.sign_file(os.path.join(self.folder, 'Release.gpg'), release, detach=True)
