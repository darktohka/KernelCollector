from deb_pkg_tools.package import inspect_package_fields
from looseversion import LooseVersion
from . import utils
import shutil, logging, time, os

class PackageList(object):

    def __init__(self, logger, repo_path, gpg_key, gpg_password):
        self.logger = logger
        self.gpg_key = gpg_key
        self.gpg_password = gpg_password
        self.distributions = {}
        self.recently_added = {}
        self.set_repo_path(repo_path)

    def set_repo_path(self, repo_path):
        self.repo_path = repo_path
        self.src_folder = os.path.join(self.repo_path, 'source')
        self.pool_folder = os.path.join(self.repo_path, 'pool', 'main')
        self.dist_folder = os.path.join(self.repo_path, 'dists')

    def add_distribution(self, distribution):
        distribution.set_package_list(self)
        self.distributions[distribution.name] = distribution

    def add_deb_to_pool(self, filename):
        basename = os.path.basename(filename)
        logging.info(f'Adding {basename} to pool...')

        # Create the pool folder if necessary
        pool_folder = os.path.join(self.pool_folder, basename[0])

        if not os.path.exists(pool_folder):
            os.makedirs(pool_folder)

        # Remove any old deb package, and move from original location to pool
        no_ext, ext = os.path.splitext(basename)
        pool_filename = os.path.join(pool_folder, f'{no_ext}_tmp{ext}')

        if os.path.exists(pool_filename):
            os.remove(pool_filename)

        shutil.copyfile(filename, pool_filename)
        os.remove(filename)
        self.recently_added[basename] = None # Version to be filled out in get_all_releases_in_pool

    def save_all_distributions(self, letters):
        # Save all distributions
        logging.info('Saving package list...')
        releases = []

        for letter in letters:
            releases.extend(self.get_all_releases_in_pool(letter))

        for distribution in self.distributions.values():
            distribution.save(releases)

    def send_embedded_report(self):
        description = [f'**{filename}** has been updated to **v{version}**!' for filename, version in self.recently_added.items() if version is not None]

        if not description:
            return

        description = '\n'.join(description)
        current_date = time.strftime('%Y-%m-%d %H:%M:%S')
        content = {
            'embeds': [{
                'title': 'Your package list has been updated!',
                'description': description,
                'color': 7526106,
                'author': {
                    'name': 'Kernel Collector',
                    'url': 'https://github.com/darktohka/kernelcollector',
                    'icon_url': 'https://i.imgur.com/y6g563D.png'
                },
                'footer': {
                    'text': f'This report has been generated on {current_date}.'
                }
            }]
        }

        self.logger.add_embed(content)
        self.logger.send_all()

    def get_all_releases_in_pool(self, letter):
        pool_folder = os.path.join(self.pool_folder, letter)

        # If we have no pool folder, there are no artifacts.
        if not os.path.exists(pool_folder):
            return []

        # Rename all _tmp files
        for file in os.listdir(pool_folder):
            if not file.endswith('_tmp.deb'):
                continue

            full_path = os.path.join(pool_folder, file)
            new_file = full_path[:-len('_tmp.deb')] + '.deb'

            if os.path.exists(new_file):
                os.remove(new_file)

            shutil.move(full_path, new_file)

        # We have to gather all packages
        pkg_to_versions = {}

        for file in sorted(os.listdir(pool_folder)):
            full_path = os.path.join(pool_folder, file)

            if not full_path.endswith('.deb'):
                os.remove(full_path)
                continue

            basename = os.path.basename(full_path)
            logging.info(f'Inspecting {basename}...')

            try:
                data = inspect_package_fields(full_path)
            except:
                os.remove(full_path)
                continue

            pkg_name = data['Package']
            version = data['Version']
            pkg = pkg_to_versions.get(pkg_name, {})

            if version in pkg:
                self.logger.add(f'Removing duplicate version {version} from package {pkg_name}...')
                self.logger.send_all()
                os.remove(full_path)
                continue

            if basename in self.recently_added:
                self.recently_added[basename] = version

            pool_filename = os.path.join(pool_folder, basename)[len(self.repo_path):].lstrip('/')
            md5, sha1, sha256 = utils.get_all_hashes(full_path)
            data['Filename'] = pool_filename
            data['Size'] = str(os.path.getsize(full_path))
            data['MD5sum'] = md5
            data['SHA1'] = sha1
            data['SHA256'] = sha256
            pkg[version] = [full_path, data]
            pkg_to_versions[pkg_name] = pkg


        releases = []

        # We need to gather the current releases now
        for pkg_name, versions in pkg_to_versions.items():
            if len(versions) == 1:
                # There is only one version, which is always the newest.
                full_path, data = list(versions.values())[0]
            else:
                # Look for the newest version
                newest_version = None
                newest_version_name = None

                for version in versions.keys():
                    if newest_version is None or LooseVersion(version) > newest_version:
                        newest_version = LooseVersion(version)
                        newest_version_name = version

                full_path, data = versions[newest_version_name]

                # Delete all previous versions from the pool
                for version, pkg_list in versions.items():
                    if version == newest_version_name:
                        continue

                    filename = pkg_list[0]
                    self.logger.add(f'Removing old file {os.path.basename(filename)}...')
                    self.logger.send_all()
                    os.remove(filename)

            releases.append([full_path, data])

        return releases
