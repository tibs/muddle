"""
Muddle utilities.
"""

import string
import re
import os
import stat
import subprocess
import socket
import time
import hashlib
import imp
import xml.dom
import xml.dom.minidom
import traceback
import pwd
import shutil
import curses
import textwrap


class Error(Exception):
    """
    Used to signal an error from muddle, which should be traced.
    """
    pass

class Failure(Exception):
    """
    Used to signal an error which shouldn't be backtraced.
    """
    pass

class Tags:
    """
    Tags commonly used by packages and dependencies.
    """
    
    # For checkouts.
    
    CheckedOut = "checked_out"
    Pulled = "pulled"
    UpToDate = "up_to_date"
    ChangesCommitted = "changes_committed"
    ChangesPushed = "changes_pushed"
    
    # For packages

    PreConfig = "preconfig"
    Configured = "configured"
    Built = "built"
    Installed = "installed"
    PostInstalled = "postinstalled"

    Clean = "clean"
    DistClean = "distclean"
    
    # For deployments. These must be independent of each other
    # and transient or deployment will get awfully confused.
    # instructionsapplied is used to separate deployment and
    # instruction application - they need to run in different
    # address spaces so that application can be privileged.
    
    Deployed = "deployed"
    InstructionsApplied = "instructionsapplied"

    # Special tag used to dynamically load extensions
    # (e.g. the build description)

    Loaded = "loaded"

    # Used to denote a temporary label that should never
    # be stored beyond the scope of the current function call
    Temporary = "temporary"

    # Used by the initscripts package to store runtime environments.
    RuntimeEnv = "runtime_env"


class LabelKind:
    """
    What sorts of objects support labels?
    """
    
    Checkout = "checkout"
    Package = "package"
    Deployment = "deployment"
    
    # Synthetic labels used purely to trick the dependency
    # mechanism into doing what I want.
    Synthetic = "synth"
    

def label_kind_to_string(val):
    """
    Convert a label kind to a string. Remember that the
    return value here is used as a directory name for
    tag tracking.
    """
    return val

class DirType:
    """
    Provides a uniform vocabulary in which we can talk about
    the types of directory we support.

    :CheckOut: denotes a source checkout.
    :Object:   denotes an object directory (one per package)
    :Deployed: denotes the deployment directory.
    :Install:  denotes an install directory.
    :Builds:   denotes the builds directory.
    :Root:     directly under the root of the build tree

    ``dict`` maps directory names to values.

    """
    CheckOut = 1
    Object = 2
    Deployed = 3
    Install = 4
    Builds = 5
    Root = 6

    
    dict = { "builds" : Builds, 
             "install" : Install, 
             "deployed" : Deployed, 
             "src"  : CheckOut, 
             "obj"  : Object }




def string_cmp(a,b):
    """
    Return -1 if a < b, 0 if a == b,  +1 if a > b.
    """
    if (a is None) and (b is None):
        return 0
    if (a is None):
        return -1
    if (b is None):
        return 1

    if (a < b):
        return -1
    elif (a==b):
        return 0
    else:
        return 1

def mark_as_domain(dir, domain_name):
    """
    Mark the build in 'dir' as a (sub)domain

    This is done by creating a file ``.muddle/am_subdomain``

    'dir' should be the path to the directory contining the sub-build's
    ``.muddle`` directory (the "top" of the sub-build).

    'dir' should thus be of the form "<somewhere>/domains/<domain_name>",
    but we do not check this.

    The given 'domain_name' is written to the file, but this should
    not be particularly trusted - refer to the containing directory
    structure for the canonical domain name.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    with open(file_name, "w") as f:
        f.write(domain_name)
        f.write("\n")

def is_subdomain(dir):
    """
    Check if the given 'dir' is a (sub)domain.

    'dir' should be the path to the directory contining the build's
    ``.muddle`` directory (the "top" of the build).

    The build is assumed to be a (sub)domain if there is a file called
    ``.muddle/am_subdomain``.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    return os.path.exists(file_name)

def get_domain_name_from(dir):
    """
    Given a directory 'dir', extract the domain name.

    'dir' should not end with a trailing slash.

    It is assumed that 'dir' is of the form "<something>/domains/<domain_name>",
    and we want to return <domain_name>.
    """
    head, domain_name = os.path.split(dir)
    head, should_be_domains = os.path.split(head)
    if should_be_domains == 'domains':
        return domain_name
    else:
        raise Error("Cannot find domain name for '%s' because it is not"
                    " '<something>/domains/<domain_name>' (unexpected '%s')"%(dir,should_be_domains))


def find_root(dir):
    """
    Find the build tree root starting at 'dir'.

    Returns a pair (dir, current_domain) - the current domain is
    the first one encountered on our way up.
    """
    
    # Normalise so path.split() doesn't produce confusing junk.
    dir = os.path.normcase(os.path.normpath(dir))
    current_domain = None

    while True:
        # Might this be a tree root?
        if os.path.exists(os.path.join(dir, ".muddle")):
            if is_subdomain(dir):
                new_domain = get_domain_name_from(dir)

                if (current_domain is None):
                    current_domain = new_domain
                else:
                    current_domain = "%s(%s)"%(new_domain,current_domain)
            else:
                return (dir, current_domain)

        up1, basename = os.path.split(dir)
        if up1 == dir or dir == '/':    # We're done
            break

        dir = up1

    # Didn't find a directory.
    return (None, None)


def get_all_checkouts_below(builder, dir):
    """
    Check all checkouts to see if their directories are
    at or below dir.
    """
    rv = [ ]
    all_cos = builder.invocation.all_checkouts()
    
    for co in all_cos:
        co_dir = builder.invocation.checkout_path(co)
        # Is it below dir? If it isn't, os.path.relpath() will
        # start with .. ..
        rp = os.path.relpath(co_dir, dir)
        if (rp[0:2] != ".."):
            # It's relative
            rv.append(co)

    return rv



def find_local_packages(dir, root, inv):
    """
    This is slightly horrible because if you're in a source checkout
    (as you normally will be), there could be several packages. 

    Returns a list of the package names (or package/role names) involved.
    """

    tloc = find_location_in_tree(dir, root, inv)
    if (tloc is None):
        return None

    (what, loc, role) = tloc

    
    if (what == DirType.CheckOut):
        rv = [  ]
        if loc is None:
            return None

        for p in inv.packages_for_checkout(loc):
            if (p.role is None):
                rv.append(p.name)
            else:
                rv.append("%s{%s}"%(p.name, p.role))
        return rv
    elif (what == DirType.Object):
        if (role is not None):
            return [ "%s{%s}"%(loc, role) ]
        else:
            return [ loc ]
    else:
        return None


def find_location_in_tree(dir, root, invocation = None):
    """
    Find the directory type and name of subdirectory in a repository.
    This is mainly used by find_local_packages to work out which
    packages to rebuild

    * dir - The directory to analyse
    * root - The root directory.

    Returns a tuple (DirType, pkg_name, role_name) or None if no information
    can be gained.
    """

    dir = os.path.normcase(os.path.normpath(dir))
    root = os.path.normcase(os.path.normpath(root))
    
    if (dir == root):
        return (DirType.Root, root, None)

    # Dir is (hopefully) a bit like 
    # root / X , so we walk up it  ...
    rest = [ ]
    while dir != '/':
        (base, cur) = os.path.split(dir)
        # Prepend .. 
        rest.insert(0, cur)
        
        if (base == root):
            # Rest is now the rest of the path.
            if (len(rest) == 0):
                # We were at the root
                return (DirType.Root, dir, None)
            else:
                # We weren't
                sub_dir = None

                if (len(rest) > 1):
                    sub_dir = rest[1]
                else:
                    sub_dir = None
                    
                #print "Infer: rest = %s sub_dir = %s "%(" ".join(rest), sub_dir)

                if (rest[0] == "src"):
                    if (len(rest) > 1) and (invocation is not None):
                        # Now, this could be a two-level checkout. There's little way to 
                        # know, beyond that if rest[1:n] is the rest of the checkout path
                        # it must be our checkout.
                        for i in range(2, len(rest)+1):
                            rel_path = rest[1:i]
                            putative_name = rest[i-1]
                            if (invocation.has_checkout_called(putative_name)):
                                #print "rel_path = %s n = %s"%(rel_path,putative_name)
                                db_path = invocation.db.get_checkout_path(putative_name, isRelative = True)
                                check_path = ""
                                for x in rel_path:
                                    check_path = os.path.join(check_path, x)

                                    #print "check_path %s db_path %s"%(check_path, db_path)
                                    if (check_path == db_path):
                                        return (DirType.CheckOut, putative_name, None)

                    
                    # If, for whatever reason, we haven't already found this package .. 
                    return (DirType.CheckOut, sub_dir, None)

                elif (rest[0] == "obj"):
                    if (len(rest) > 2):
                        role = rest[2]
                    else:
                        role = None
                    
                    return (DirType.Object, sub_dir, role)
                elif (rest[0] == "install"):
                    return (DirType.Install, sub_dir, None)
                elif (rest[0] == "domains"):
                    # We're inside the current domain - this is actually a root
                    return (DirType.Root, dir, None)
                else:
                    return None
        else:
            dir = base

    return None

def ensure_dir(dir, verbose=True):
    """
    Ensure that dir exists and is a directory, or throw an error.
    """
    if os.path.isdir(dir):
        return True
    elif os.path.exists(dir):
        raise Error("%s exists but is not a directory"%dir)
    else:
        if verbose:
            print "> Make directory %s"%dir
        os.makedirs(dir)

def pad_to(str, val, pad_with = " "):
    """
    Pad the given string to the given number of characters with the given string.
    """
    to_pad = (val - len(str)) / len(pad_with)
    arr =  [ str ]
    for i in range(0, to_pad):
        arr.append(pad_with)

    return "".join(arr)


def unix_time():
    """
    Return the current UNIX time since the epoch.
    """
    return int(time.time())

def iso_time():
    """
    Retrieve the current time and date in ISO style ``YYYY-MM-DD HH:MM:SS``.
    """
    return time.strftime("%Y-%m-%d %H:%M:%S")

def current_user():
    """
    Return the identity of the current user, as an email address if possible,
    but otherwise as a UNIX uid
    """
    uid = os.getuid()
    a_pwd = pwd.getpwuid(uid)
    if (a_pwd is not None):
        return a_pwd.pw_name
    else:
        return None

def current_machine_name():
    """
    Return the identity of the current machine - possibly including the 
    domain name, possibly not
    """
    return socket.gethostname()
    
    

def run_cmd(cmd, env = None, allowFailure = False, isSystem = False,
            verbose = True):
    """
    Run a command via the shell, raising an exception on failure,

    * env is the environment to use when running the command.  If this is None,
      then ``os.environ`` is used.
    * if allowFailure is true, then failure of the command will be ignored.
    * otherwise, isSystem is used to decide what to do if the command fails.
      If isSystem is true, then this is a command being run by the system and
      failure should be reported by raising utils.Error. otherwise, it's being
      run on behalf of the user and failure should be reported by raising
      utils.Failure.
    * if verbose is true, then print out the command before executing it

    Return the exit code of this command.
    """
    if env is None: # so, for instance, an empty dictionary is allowed
        env = os.environ
    if verbose:
        print "> %s"%cmd
    rv = subprocess.call(cmd, shell = True, env = env)
    if allowFailure or rv == 0:
        return rv
    else:
        if isSystem:
            raise Error("Command '%s' execution failed - %d"%(cmd,rv))
        else:
            raise Failure("Command '%s' execution failed - %d"%(cmd,rv))


def get_cmd_data(cmd, env=None, isSystem=False, fold_stderr=True,
                 verbose=False, fail_nonzero=True):
    """
    Run the given command, and return its (returncode, stdout, stderr).

    If 'fold_stderr', then "fold" stderr into stdout, and return
    (returncode, stdout_data, NONE).

    If 'fail_nonzero' then if the return code is non-0, raise an explanatory
    exception (Error is 'isSystem', otherwise Failure).

    And yes, that means the default use-case returns a tuple of the form
    (0, <string>, None), but otherwise it gets rather awkward handling all
    the options.
    """
    if env is None:
        env = os.environ
    if verbose:
        print "> %s"%cmd
    p = subprocess.Popen(cmd, shell=True, env=env,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if fold_stderr
                                                  else subprocess.PIPE)
    stdoutdata, stderrdata = p.communicate()
    returncode = p.returncode
    if fail_nonzero and returncode:
        if isSystem:
            raise Error("Command '%s' execution failed - %d"%(cmd,rv))
        else:
            raise Failure("Command '%s' execution failed - %d"%(cmd,rv))
    return returncode, stdoutdata, stderrdata


def indent(text, indent):
    """Return the text indented with the 'indent' string.

    (i.e., place 'indent' in front of each line of text).
    """
    lines = text.split('\n')
    stuff = []
    for line in lines:
        stuff.append('%s%s'%(indent,line))
    return '\n'.join(stuff)

def wrap(text):
    """A convenience wrapper around textwrap.wrap()

    (basically because muddled users will have imported utils already).
    """
    return "\n".join(textwrap.wrap(text))

def num_cols():
    """How many columns on our terminal?

    Returns a negative number on error.
    """
    curses.setupterm()
    return curses.tigetnum('cols')

def truncate(text, columns=None, less=0):
    """Truncate the given text to fit the terminal.

    More specifically:

    1. Split on newlines
    2. If the first line is too long, cut it and add '...' to the end.
    3. Return the first line

    If 'columns' is 0, then don't do the truncation of the first line.

    If 'columns' is None, then try to work out the current terminal width
    (using "curses"), and otherwise use 80.

    If 'less' is specified, then the actual width used will be the calculated
    or given width, minus 'less' (so if columns=80 and less=2, then the maximum
    line length would be 78). Clearly this is ignored if 'columns' is 0.
    """
    text = text.split('\n')[0]
    if columns == 0:
        return text

    if columns is None:
        columns = num_cols()
        if columns <= 0:
            columns = 80
    max_width = columns - less
    if len(text) > max_width:
        text = text[:max_width-3]+'...'
    return text


def dynamic_load(filename):
    mod = None
    if (filename == None):
        raise Error(\
            "Attempt to call DynamicLoad() with filename None")
    try:
        fin = open(filename, 'rb')
        contents = fin.read()
        hasher = hashlib.md5()
        hasher.update(contents)
        md5_digest = hasher.hexdigest()
        fin.close()

        mod = imp.load_source(md5_digest, filename)
    except Exception, e:
        print "Cannot load %s - %s \n"%(filename,e)
        traceback.print_exc()
        try:
            fin.close()
        except: pass
        raise Failure("Cannot load build description %s - %s"%(filename, e))

    return mod


def do_shell_quote(str):
    return maybe_shell_quote(str, True)

def maybe_shell_quote(str, doQuote):
    """
    If doQuote is False, do nothing, else shell-quote ``str``.

    Annoyingly, shell quoting things correctly must use backslashes, since
    quotes can (and will) be misinterpreted. Bah.

    """
    if doQuote:
        result = [ "" ]
        for i in str:
            if i=="\"" or i=="\\" or i=='\'':
                result.append("\\")
            result.append(i)
        result.append("")

        return "".join(result)
    else:
        return str

def text_in_node(in_xml_node):
    """
    Return all the text in this node.
    """
    in_xml_node.normalize()
    return_list = [ ]
    for c in in_xml_node.childNodes:
        if (c.nodeType == xml.dom.Node.TEXT_NODE):
            return_list.append(c.data)

    return "".join(return_list)


def recursively_remove(a_dir):
    """
    Recursively demove a directory.
    """
    if (os.path.exists(a_dir)):
        # Again, the most efficient way to do this is to tell UNIX to do it
        # for us.
        run_cmd("rm -rf \"%s\""%(a_dir))


def copy_file_metadata(from_path, to_path):
    """
    Copy file metadata.
    
    If 'to_path' is a link, then it tries to copy whatever it can from
    'from_path', treated as a link.

    If 'to_path' is not a link, then it copies from 'from_path', or, if
    'from_path' is a link, whatever 'from_path' references.

    Metadata is: mode bits, atime, mtime, flags and (if the process has an
    effective UID of 0) the ownership (uid and gid).
    """

    if os.path.islink(to_path):
        st = os.lstat(from_path)

        if hasattr(os, 'lchmod'):
            mode = stat.S_IMODE(st.st_mode)
            os.lchmod(to_path, mode)

        if hasattr(os, 'lchflags'):
            os.lchflags(to_path, st.st_flags)

        if os.geteuid() == 0 and hasattr(os, 'lchown'):
            os.lchown(to_path, s.st_uid, s.st_gid)
    else:
        st = os.stat(from_path)
        mode = stat.S_IMODE(st.st_mode)
        os.chmod(to_path, mode)
        os.utime(to_path, (st.st_atime, st.st_mtime))
        if hasattr(os, 'chflags'):
            os.chflags(to_path, st.st_flags)
        if os.geteuid() == 0:
            os.chown(to_path, s.st_uid, s.st_gid)

def copy_file(from_path, to_path, object_exactly=False, preserve=False):
    """
    Copy a file (either a "proper" file, not a directory, or a symbolic link).

    Just like recursively_copy, only not recursive :-)

    If the target file already exists, it is overwritten.

       Caveat: if the target file is a directory, it will not be overwritten.
       If the source file is a link, being copied as a link, and the target
       file is not a link, it will not be overwritten.

    If 'object_exactly' is true, then if 'from_path' is a symbolic link, it
    will be copied as a link, otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').
    """

    if object_exactly and os.path.islink(from_path):
        linkto = os.readlink(from_path)
        if os.path.islink(to_path):
            os.remove(to_path)
        os.symlink(linkto, to_path)
    else:
        shutil.copyfile(from_path, to_path)

    if preserve:
        copy_file_metadata(from_path, to_path)

def recursively_copy(from_dir, to_dir, object_exactly=False, preserve=True):
    """
    Take everything in from_dir and copy it to to_dir, overwriting
    anything that might already be there.

    Dot files are included in the copying.

    If object_exactly is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If preserve is true, then the file's mode, ownership and timestamp will be
    copied, if possible. This is only really useful when copying as a
    privileged user.
    """
    
    copy_without(from_dir, to_dir, object_exactly=object_exactly,
                 preserve=preserve)


def split_path_left(in_path):
    """
    Given a path ``a/b/c ...``, return a pair
    ``(a, b/c..)`` - ie. like ``os.path.split()``, but leftward.

    What we actually do here is to split the path until we have
    nothing left, then take the head and rest of the resulting list.

    For instance:

        >>> split_path_left('a/b/c')
        ('a', 'b/c')
        >>> split_path_left('a/b')
        ('a', 'b')

    For a single element, behave in sympathy (but, of course, reversed) to
    ``os.path.split``:

        >>> import os
        >>> os.path.split('a')
        ('', 'a')
        >>> split_path_left('a')
        ('a', '')

    The empty string isn't really a sensible input, but we cope:

        >>> split_path_left('')
        ('', '')

    And we take some care with delimiters (hopefully the right sort of care):

        >>> split_path_left('/a///b/c')
        ('', 'a/b/c')
        >>> split_path_left('//a/b/c')
        ('', 'a/b/c')
        >>> split_path_left('///a/b/c')
        ('', 'a/b/c')
    """

    if not in_path:
        return ('', '')

    # Remove redundant sequences of '//'
    # This reduces paths like '///a//b/c' to '/a/b/c', but unfortunately
    # it leaves '//a/b/c' untouched
    in_path = os.path.normpath(in_path)
    
    remains = in_path
    lst = [ ]

    while remains and remains not in ("/", "//"):
        remains, end = os.path.split(remains)
        lst.append(end)

    if remains in ("/", "//"):
        lst.append("")

    # Our list is in reverse order, so ..
    lst.reverse()

    if False:
        rp = lst[1]
        for i in lst[2:]:
            rp = os.path.join(rp, i)
    else:
        if len(lst) > 1:
            rp = os.path.join(*lst[1:])
        else:
            rp = ""

    return (lst[0], rp)
    

def print_string_set(ss):
    """
    Given a string set, return a string representing it.
    """
    result = [ ]
    for s in ss:
        result.append(s)

    return " ".join(result)

def c_escape(v):
    """
    Escape sensitive characters in v.
    """
    
    return re.sub(r'([\r\n"\'\\])', r'\\\1', v)

def replace_root_name(base, replacement, filename):
    """
    Given a filename, a base and a replacement, replace base with replacement
    at the start of filename.    
    """
    #print "replace_root_name %s, %s, %s"%(base,replacement, filename)
    base_len = len(base)
    if (filename.startswith(base)):
        left = replacement + filename[base_len:]
        if len(left) > 1 and left[:2] == '//':
            left = left[1:]
        return left
    else:
        return filename


def parse_mode(in_mode):
    """
    Parse a UNIX mode specification into a pair (clear_bits, set_bits).
    """

    # Annoyingly, people do write modes as '6755' etc..
    if (in_mode[0] >= '0' and in_mode[0] <= '9'):
        # It's octal.
        clear_bits = 07777
        set_bits = int(in_mode, 8)

        return (clear_bits, set_bits)
    else:
        # @todo Parse symbolic modes here.
        raise Failure("Unsupported UNIX modespec %s"%in_mode)

def parse_uid(builder, text_uid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming 
               your uid is numeric
    """
    return int(text_uid)

def parse_gid(builder, text_gid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming 
               your gid is numeric
    """
    return int(text_gid)
        

def xml_elem_with_child(doc, elem_name, child_text):
    """
    Return an element 'elem_name' containing the text child_text in doc.
    """
    el = doc.createElement(elem_name)
    el.appendChild(doc.createTextNode(child_text))
    return el


def _copy_without(src, dst, ignored_names, object_exactly, preserve):
    """
    The insides of copy_without. See that for more documentation.

    'ignored_names' must be a sequence of filenames to ignore (but may be empty).
    """

    # Inspired by the example for shutil.copytree in the Python 2.6 documentation

    names = os.listdir(src)

    if True:
        ensure_dir(dst, verbose=False)
    else:
        if not os.path.exists(dst):
            os.makedirs(dst)

    for name in names:
        if name in ignored_names:
            continue

        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if object_exactly and os.path.islink(srcname):
                copy_file(srcname, dstname, object_exactly=True, preserve=preserve)
            elif os.path.isdir(srcname):
                _copy_without(srcname, dstname, ignored_names=ignored_names,
                              object_exactly=object_exactly, preserve=preserve)
            else:
                copy_file(srcname, dstname, object_exactly=object_exactly, preserve=preserve)
        except (IOError, os.error), why:
            raise Failure('Unable to copy %s to %s: %s'%(srcname, dstname, why))

    try:
        copy_file_metadata(src, dst)
    except OSError, why:
        raise Failure('Unable to copy properties of %s to %s: %s'%(src, dst, why))

def copy_without(src, dst, without=None, object_exactly=True, preserve=False):
    """
    Copy without entries in the sequence 'without'.

    If given, 'without' should be a sequence of filenames - for instance,
    ['.bzr', '.svn'].

    If 'object_exactly' is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will be
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').

    Creates directories in the destination, if necessary.

    Uses copy_file() to copy each file.
    """

    if without is not None:
        ignored_names = without
    else:
        ignored_names = set()

    print 'Copying %s to %s'%(src, dst),
    if without:
        print 'ignoring %s'%without
    print

    _copy_without(src, dst, ignored_names, object_exactly, preserve)

def copy_name_list_with_dirs(file_list, old_root, new_root,
                             object_exactly = True, preserve = False): 
    """

    Given file_list, create file_list[new_root/old_root], creating
    any directories you need on the way.
    
    file_list is a list of full path names.
    old_root is the old root directory
    new_root is where we want them copied
    """
    for f in file_list:
        tgt_name = replace_root_name(old_root, new_root, f)
        target_dir = os.path.dirname(tgt_name)
        ensure_dir(target_dir)
        copy_file(f, tgt_name, object_exactly, preserve)


def get_prefix_pair(prefix_one, value_one, prefix_two, value_two):
    """
    Returns a pair (prefix_onevalue_one, prefix_twovalue_two) - used
    by rrw.py as a utility function
    """
    return ("%s%s"%(prefix_one, value_one), "%s%s"%(prefix_two, value_two))

def rel_join(vroot, path):
    """
    Find what path would be called if it existed inside vroot. Differs from
    os.path.join() in that if path contains a leading '/', it is not
    assumed to override vroot.

    If vroot is none, we just return path.
    """

    if (vroot is None): 
        return path

    if (len(path) == 0): 
        return vroot

    if path[0] == '/':
        path = path[1:]
    
    return os.path.join(vroot, path)

    
def split_domain(domain_name):
    """
    Given a domain name, return a tuple of the hierarchy of sub-domains.

    For instance:

        >>> split_domain('a')
        ['a']
        >>> split_domain('a(b)')
        ['a', 'b']
        >>> split_domain('a(b(c))')
        ['a', 'b', 'c']
        >>> split_domain('a(b(c)')
        Traceback (most recent call last):
        ...
        Failure: Domain name "a(b(c)" has mis-matched parentheses

    We don't actually allow "sibling" sub-domains, so we try to complain
    helpfully:

        >>> split_domain('a(b(c)(d))')
        Traceback (most recent call last):
        ...
        Failure: Domain name "a(b(c)(d))" has 'sibling' sub-domains
    """

    if '(' not in domain_name:
        return [domain_name]

    if ')(' in domain_name:
        raise Failure('Domain name "%s" has '
                      "'sibling' sub-domains"%domain_name)

    parts = domain_name.split('(')

    num_closing = len(parts) - 1
    if not parts[-1].endswith( num_closing * ')' ):
        raise Failure('Domain name "%s" has mis-matched parentheses'%domain_name)

    parts[-1] = parts[-1][:- num_closing]
    return parts

def domain_subpath(domain_name):
    """Calculate the sub-path for a given domain name.

    For instance:

        >>> domain_subpath('a')
        'domains/a'
        >>> domain_subpath('a(b)')
        'domains/a/domains/b'
        >>> domain_subpath('a(b(c))')
        'domains/a/domains/b/domains/c'
        >>> domain_subpath('a(b(c)')
        Traceback (most recent call last):
        ...
        Failure: Domain name "a(b(c)" has mis-matched parentheses
    """
    parts = []
    for thing in split_domain(domain_name):
        parts.append('domains')
        parts.append(thing)
    
    return os.path.join(*parts)


gArchName = None

def arch_name():
    """
    Retrieve the name of the architecture on which we're running.
    Some builds require packages to be built on a particular (odd) architecture.
    """
    global gArchName

    if (gArchName is None):
        # This is what the docs say you should do. Ugh.
        x = subprocess.Popen(["uname", "-m"], stdout=subprocess.PIPE).communicate()[0]
        gArchName = x.strip()

    return gArchName


def unescape_backslashes(str):
    """
    Replace every string '\\X' with X, as if you were a shell
    """
    
    wasBackslash = False
    result = [ ]
    for i in str:
        if (wasBackslash):
            result.append(i)
            wasBackslash = False
        else:
            if (i == '\\'):
                wasBlackslash = True
            else:
                result.append(i)

    return "".join(result)



def quote_list(lst):
    """
    Given a list, quote each element of it and return them, space separated
    """
    return " ".join(map(do_shell_quote, lst))


def unquote_list(lst):
    """
    Given a list of objects, potentially enclosed in quotation marks or other
    shell weirdness, return a list of the actual objects.
    """
    
    # OK. First, dispose of any enclosing quotes.
    result = [ ]
    lst = lst.strip()
    if (lst[0] == '\'' or lst[0] == "\""):
        lst = lst[1:-1]

    initial = lst.split(' ')
    last = None
    
    for i in initial:
        if (last is not None):
            last = last + i
        else:
            last = i

        # If last ended in a backslash, round again
        if (len(last) > 0 and last[-1] == '\\'):
            last = last[:-1]
            continue

        # Otherwise, dump it, unescaping everything else
        # as we do so
        result.append(unescape_backslashes(last))
        last = None

    if (last is not None):
        result.append(unescape_backslashes(last))

    return result

def find_by_predicate(source_dir, accept_fn, links_are_symbolic = True):
    """
    Given a source directory and an acceptance function
     fn(source_base, file_name) -> result
    
    Obtain a list of [result] if result is not None.
    """

    result = [ ]

    r = accept_fn(source_dir)
    if (r is not None):
        result.append(r)

    
    if (links_are_symbolic and os.path.islink(source_dir)):
        # Bah
        return result

    if (os.path.isdir(source_dir)):
        # We may need to recurse...
        names = os.listdir(source_dir)
        
        for name in names:
            full_name = os.path.join(source_dir, name)
            r = accept_fn(full_name)
            if (r is not None):
                result.append(r)

            # os.listdir() doesn't return . and .. 
            if (os.path.isdir(full_name)):
                result.extend(find_by_predicate(full_name, accept_fn, links_are_symbolic))

    return result

def calc_file_hash(filename):
    """Calculate and return the SHA1 hash for the named file.
    """
    with HashFile(filename) as fd:
        for line in fd:
            pass
    return fd.hash()

class HashFile(object):
    """
    A very simple class for handling files and calculating their SHA1 hash.

    We support a subset of the normal file class, but as lines are read
    or written, we calculate a SHA1 hash for the file.
    """

    def __init__(self, name, mode='r'):
        """
        Open the file, for read or write.
        """
        if mode not in ('r', 'w'):
            raise ValueError("HashFile 'mode' must be one of 'r' or 'w', not '%s'"%mode)
        self.name = name
        self.mode = mode
        self.fd = open(name, mode)
        self.sha = hashlib.sha1()

    def write(self, text):
        r"""
        Write the give text to the file, and add it to the SHA1 hash as well.

        As is normal for file writes, the '\n' at the end of a line must be
        specified.
        """
        if self.mode != 'w':
            raise Error("Cannot write to HashFile '%s', opened for read"%self.name)
        self.fd.write(text)
        self.sha.update(text)

    def readline(self):
        """
        Read the next line from the file, and add it to the SHA1 hash as well.

        Returns '' if there is no next line (i.e., EOF is reached).
        """
        if self.mode != 'r':
            raise Error("Cannot read from HashFile '%s', opened for write"%self.name)
        text = self.fd.readline()

        if text == '':
            return ''
        else:
            self.sha.update(text)
            return text

    def hash(self):
        """
        Return the SHA1 hash, calculated from the lines so far, as a hex string.
        """
        return self.sha.hexdigest()

    def close(self):
        """
        Close the file.
        """
        self.fd.close()

    # Support for "with"
    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close()
        else:
            # An exception occurred, so do any tidying up necessary
            # - well, there isn't anything special to do, really
            self.close()
            # And allow the exception to be re-raised
            return False

    # Support for iteration (over lines)
    def __iter__(self):
        if self.mode != 'r':
            raise Error("Cannot iterate over HashFile '%s', opened for write"%self.name)
        return self

    def next(self):
        text = self.readline()
        if text == '':
            raise StopIteration
        else:
            return text
    
# End file.
