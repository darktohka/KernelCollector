# KernelCollector

KernelCollector is a small Python script that handles the upkeep of a Linux kernel Debian package repository.

It keeps track of header, image and module packages for the `amd64`, `i386`, `armhf`, `arm64`, `ppc64el` and `s390x` architectures.

There are three kind of kernel images that KernelCollector collects:
 * `linux-current`: The newest stable version of the Linux kernel, for example: `v5.8.10`
 * `linux-beta`: The newest release candidate of the Linux kernel, for example: `v5.9-rc5`
 * `linux-devel`: The newest trunk build of the Linux kernel, for example: `v2019-09-17`

Using a cronjob, KernelCollector can always keep these packages updated in the Debian package repository.

This is useful because it allows users to automatically upgrade their Linux kernels to the latest version from the update channel, without any user input. For example, you will not receive beta or devel versions while on the current release channel.

Older kernel versions will disappear once the newest kernel is installed. If kernel version `5.8.10` is released, everybody using the KernelCollector repository will automatically be upgraded to version `5.8.10`, straight from `5.8.9` - and so on.

This kind of setup might not be useful (or too risky) for some people, in that case, you are welcome to handle your own kernel installations.


## Getting started: User Guide


Users will simply have to install the official `https://deb.tohka.us` Debian package repository, by dropping the package list into `/etc/apt/sources.list.d` (or straight into `/etc/apt/sources.list`, if you'd like), and then importing the GPG key that the Linux kernel packages are signed with.

```
echo "deb [signed-by=/usr/share/keyrings/kernelcollector-archive-keyring.gpg] https://deb.tohka.us sid main" | sudo tee /etc/apt/sources.list.d/tohka.list
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/kernelcollector-archive-keyring.gpg --keyserver keyserver.ubuntu.com --recv-keys E4012B02CD659038
sudo apt update
```

After installing the repository, decide which release channel you want to follow.

`linux-current` will follow the stable release of the Linux kernel.

`linux-beta` will follow the release candidates of the Linux kernel.

`linux-devel` will follow the daily trunk build of the Linux kernel. Usage of the linux-devel packages is usually not a good idea, as these packages are 100% untested and incredibly bleeding-edge.

You'll also have to find out what your architecture is, for example: `amd64`

Here's an example: how to install `linux-current` on `amd64`?

```
sudo apt update
sudo apt install linux-current-headers-all linux-current-headers-generic-amd64 linux-current-image-generic-amd64 linux-current-modules-generic-amd64
```

That's it, restart, and you're done! You might want to consider removing your previous kernel packages. Combine `dpkg --list | grep linux-` and `apt purge` to achieve this.


## Getting Started: Developer Guide


What if you want to run your own Linux kernel package list?

It's simple: first, get a domain (or subdomain) that you will run your package list on. Then, install Python 3.7+ and nginx (or any web server of your choice) on your server.

Clone the project, install the Python requirements, and run the project once to generate your `settings.json` file:

```
git clone https://github.com/darktohka/KernelCollector
python3 -m pip install -r requirements.py
sudo sh run.sh
```

Next, edit the `settings.json` file to your liking:

* `architectures`: Defaults to `"amd64", "i386"`. These are the architectures that your package list will track. Possible values: `"amd64", "i386", "armhf", "arm64", "ppc64el", "390x"`
* `description`: Defaults to `Package repository for newest Linux kernels`. This is just a short description of your repository.
* `distribution`: Defaults to `sid`. This really doesn't matter, as the packages require a newer version of Debian or Ubuntu, and this is just a matter of preference.
* `gpgKey`: Defaults to `ABCD`. Obviously, this isn't a real GPG key. Repositories maintained by KernelCollector are GPG signed. You will have to create your own GPG key, which can be password protected if needed.
* `gpgPassword`: Defaults to `none`. If you don't have a GPG password, please set the password to `none`. If you have one, specify it here.
* `repoPath`: Defaults to `/srv/packages`. This is the filesystem path of your repository, where the artifacts will be published to.
* `webhook`: Defaukts to `None`. If you have a Discord channel, please consider setting this variable. Package reports are automatically sent to Discord.

You might notice that you need a GPG key to sign the kernel packages. This is out of scope for this tutorial, Google is your friend in this regard, though `gpg --full-generate-key` might be a good point to start.

Next, run the package collector for the first time:

```
sudo sh run.sh
```

After running the package collector, your packages will have already been published to your repository. To make this repository accessible from the internet, however, you'll need a web server.

An example config for nginx can be found in the `supplementary` folder, but changes might need to be made if you desire SSL support.

After setting up a web server, you'll need to create a cronjob to automatically run KernelCollector, checking for new kernel versions. Make sure to set this cronjob to run as root.

```
sudo crontab -e
```

Here's an example crontab configuration that will run KernelCollector installed in `/star/pkglist` every hour:

```
0 * * * * /bin/bash /star/pkglist/run.sh >/dev/null 2>&1
```

And that's all there's to it! You might want to publish your GPG keys to a key server, such as `keyserver.ubuntu.com`:

```
gpg --keyserver keyserver.ubuntu.com --send-keys ABCDEFGH
```


## Docker Guide

KernelCollector can be ran using Docker. First, build the image.

```
git clone git@github.com:darktohka/KernelCollector .
docker build . -t kernelcollector
```

To run the image straight from Docker Hub, pull the image from there instead.

```
docker pull darktohka/kernelcollector:latest
```

Next, export your GPG key to a file named `gpg.key`. Use `gpg --export-secret-keys KEY_ID` to accomplish this.

Afterwards, run the image inside a container. Make sure to mount your GPG key:

```
chown 423:423 settings.json cache.json
chown -R 423:423 packages
docker run -d --name kernelcollector -v "$(pwd)/cache.json:/srv/cache.json" -v "$(pwd)/settings.json:/srv/settings.json" -v "$(pwd)/packages:/srv/packages" -v "$(pwd)/gpg.key:/srv/gpg.key" kernelcollector
```
