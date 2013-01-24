"""
An apt-get package. When you try to build it, this package
pulls in a pre-canned set of packages via apt-get.
"""

import muddled.pkg as pkg
import muddled.depend as depend
import muddled.utils as utils
import subprocess


class AptGetBuilder(pkg.PackageBuilder):
    """
    Build an apt-get package.
    """

    def __init__(self, name, role,  pkgs_to_install):
        pkg.PackageBuilder.__init__(self, name, role)
        self.pkgs_to_install = pkgs_to_install

    def already_installed(self, pkg):
        """
        Decide if the quoted debian package is already installed.

        We use dpkg-query::

            $ dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' libreadline-dev
            ii  libreadline-dev

        That second 'i' means installed. Contrast with a package that is
        either not recognised or has not been downloaded at all::

            $ dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' a0d
            dpkg-query: no packages found matching a0d

        So we do some fairly simple processing of the output...
        """
        process = subprocess.Popen([ "dpkg-query",
                                     "-W",
                                     "-f='${db:Status-Abbrev} ${Package}\\n'",
                                     pkg ],
                                   stdout = subprocess.PIPE,
                                   stderr = subprocess.PIPE)
        (stdout_data, stderr_data) = process.communicate()
        process.wait()
        lines = stdout_data.splitlines()
        for l in lines:
            fields = l.split()
            if len(fields) == 2:
                status = fields[0]
                name = fields[1]
                if name == pkg and status[1] == 'i':
                    return True
        return False


    def build_label(self, builder, label):
        """
        This time, build is the only one we care about.
        """

        if (label.tag == utils.LabelTag.Built):
            need_to_install = [ ]

            for cur_pkg in self.pkgs_to_install:
                if (not self.already_installed(cur_pkg)):
                    need_to_install.append(cur_pkg)

            if (len(need_to_install) > 0):
                cmd_list = [ "sudo", "apt-get", "install" ]
                cmd_list.extend(need_to_install)
                print "> %s"%(" ".join(cmd_list))
                rv = subprocess.call(cmd_list)
                if rv != 0:
                    raise utils.GiveUp("Couldn't install required packages")

            print ">> Installed %s"%(" ".join(self.pkgs_to_install))


def simple(builder, name, role, apt_pkgs):
    """
    Construct an apt-get package in the given role with the given apt_pkgs.
    """

    the_pkg = AptGetBuilder(name, role, apt_pkgs)
    pkg.add_package_rules(builder.ruleset,
                          name, role, the_pkg)


def depends_on_aptget(builder, name, role, pkg, pkg_role):
    """
    Make a package dependant on a particular apt-builder.

    * pkg - The package we want to add a dependency to. '*' is a good thing to
      add here ..
    """

    tgt_label = depend.Label(utils.LabelType.Package,
                             pkg,  pkg_role,
                             utils.LabelTag.PreConfig)

    the_rule = builder.ruleset.rule_for_target(tgt_label,
                                                          createIfNotPresent = True)
    the_rule.add(depend.Label(utils.LabelType.Package,
                              name, role,
                              utils.LabelTag.PostInstalled))


def medium(builder, name, role, apt_pkgs, roles):
    """
    Construct an apt-get package and make every package in the named roles
    depend on it.
    """
    simple(builder, name, role, apt_pkgs)
    for dep_role in roles:
        depends_on_aptget(builder, name, role, "*", dep_role)




# End file.

