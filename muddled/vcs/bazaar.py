"""
Muddle support for Bazaar.
"""

from muddled.version_control import *
import muddled.utils as utils

class Bazaar(VersionControlHandler):
    """
    Version control handler for bazaar.

    Bazaar repositories are named: bzr+<url>.

    It's assumed that the first path component of 'rel' is the name of the repository.
    """

    def __init__(self, inv, co_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, inv, co_name, repo, rev, rel, co_dir)
        
        sp = conventional_repo_url(repo, rel)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, co %s"%(repo, rel))

        self.bzr_repo = sp[0]
        self.co_path = self.get_checkout_path(None)

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        # Check out.
        utils.ensure_dir(self.co_path)
        os.chdir(self.co_path)
        utils.run_cmd("bzr co %s %s %s"%(self.r_option(), self.bzr_repo, self.checkout_name))
        os.chdir(self.co_path)
        utils.run_cmd("bzr unbind")

    def pull(self):
        os.chdir(self.co_path)
        utils.run_cmd("bzr pull %s"%self.bzr_repo)

    def update(self):
        os.chdir(self.co_path)
        utils.run_cmd("bzr update", allowFailure = True)

    def commit(self):
        os.chdir(self.co_path)
        utils.run_cmd("bzr commit")

    def push(self):
        os.chdir(self.co_path)
        utils.run_cmd("bzr push %s"%self.bzr_repo)

    def must_update_to_commit(self):
        return False

    def r_option(self):
        """
        Return the -r option to pass to bzr commands, if any
        """
        if ((self.revision is None) or (self.revision == "HEAD")):
            return ""
        else:
            return "-r %s"%(self.revision)


class BazaarVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "The Bazaar VCS"

    def manufacture(self, inv, co_name, repo, rev, rel, co_dir):
        return Bazaar(inv, co_name, repo, rev, rel, co_dir)

        
# Tell the version control handler about us..
register_vcs_handler("bzr", BazaarVCSFactory())

# End file.

