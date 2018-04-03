from github import Github

import base64
import config
import frontmatter
import json
import logging
import os
import re
import webapp2

FILE_RE = re.compile("^EIPS/eip-(\d+).md$")
AUTHOR_RE = re.compile("[(<]([^>)]+)[>)]")
MERGE_MESSAGE = """
Hi, I'm a bot! This change was automatically merged because:

 - It only modifies existing draft EIP(s)
 - The creator of this PR is listed as an author on all modified EIP(s)
 - The build is passing
"""

github = Github(config.GITHUB_ACCESS_TOKEN)

class MergeHandler(webapp2.RequestHandler):
    def check_authors(self, authorlist, username, email):
        for author in AUTHOR_RE.finditer(authorlist):
            author = author.groups(1)[0]
            if author.startswith("@") and author[1:] == username: return True
            if author == email: return True
        return False

    def check_file(self, pr, file):
        try:
            match = FILE_RE.search(file.filename)
            if not match:
                return ((), "File %s is not an EIP" % (file.filename,))
            eipnum = int(match.group(1))

            if file.status == "added":
                return ((), "Contains new file %s" % (file.filename,))

            logging.info("Getting file %s from %s@%s/%s", file.filename, pr.base.user.login, pr.base.repo.name, pr.base.sha)
            base = pr.base.repo.get_contents(file.filename, ref=pr.base.sha)
            basedata = frontmatter.loads(base64.b64decode(base.content))
            if basedata.get("status") != "Draft":
                return ((), "EIP %d is in state %s, not Draft" % (eipnum, basedata.get("status")))
            if basedata.get("eip") != eipnum:
                return ((eipnum,), "EIP header in %s does not match: %s" % (file.filename, basedata.get("eip")))
            if not self.check_authors(basedata.get("author"), pr.user.login, pr.user.email):
                return ((eipnum,), "User %s is not an author of EIP %d" % (pr.user.login, eipnum))

            logging.info("Getting file %s from %s@%s/%s", file.filename, pr.head.user.login, pr.head.repo.name, pr.head.sha)
            head = pr.head.repo.get_contents(file.filename, ref=pr.head.sha)
            headdata = frontmatter.loads(base64.b64decode(head.content))
            if headdata.get("eip") != eipnum:
                return ((eipnum,), "EIP header in modified file %s does not match: %s" % (file.filename, headdata.get("eip")))
            if headdata.get("status") != "Draft":
                return ((eipnum,), "Trying to change EIP %d state from Draft to %s" % (eipnum, headdata.get("status")))

            return ((eipnum, ), None)
        except Exception, e:
            logging.exception("Exception checking file %s", file.filename)
            return ((), "Error checking file %s" % (file.filename,))

    def post(self):
        build = json.loads(self.request.get("payload"))
        logging.info("Processing build %s...", build["number"])
        if build.get("pull_request_number") is None:
            logging.info("Build %s is not a PR build; quitting", build["number"])
            return
        prnum = int(build["pull_request_number"])
        self.check_pr(build["repository"]["owner_name"] + "/" + build["repository"]["name"], prnum)

    def get(self):
        self.check_pr(self.request.get("repo"), int(self.request.get("pr")))

    def check_pr(self, reponame, prnum):
        logging.info("Checking PR %d on %s", prnum, reponame)
        repo = github.get_repo(reponame)
        pr = repo.get_pull(prnum)
        if pr.merged:
            logging.info("PR %d is already merged; quitting", prnum)
            return
        if pr.mergeable_state != 'clean':
            logging.info("PR %d mergeable state is %s; quitting", prnum, pr.mergeable_state)
            return

        eipnums = []
        reasons = []
        for file in pr.get_files():
            file_eipnums, message = self.check_file(pr, file)
            eipnums.extend(file_eipnums)
            if message is not None:
                logging.info(message)
                reasons.append(message)

        if len(reasons) == 0:
            logging.info("Merging PR %d!", prnum)
            self.response.write("Merging PR %d!" % (prnum,))
            pr.merge(
                commit_title="Automatically merged updates to draft EIP(s) %s" % (', '.join('%s' % x for x in eipnums)),
                commit_message=MERGE_MESSAGE,
                merge_method="squash",
                sha=pr.head.sha)
        elif len(reasons) > 0 and len(eipnums) > 0:
            message = "Hi! I'm a bot, and I wanted to automerge your PR, but couldn't because of the following issue(s):\n\n"
            message += "\n".join(" - " + reason for reason in reasons)

            self.post_comment(pr, message)

    def post_comment(self, pr, message):
        me = github.get_user()
        for comment in pr.get_issue_comments().reversed:
            logging.info("Comment by %s", comment.user.login)
            if comment.user.login == me.login:
                logging.info("Found comment by myself")
                if comment.body == message:
                    logging.info("Refusing to post identical message on PR %d", pr.number)
                    return
                else:
                    break
        pr.create_issue_comment(message)


app = webapp2.WSGIApplication([
    ('/merge/', MergeHandler),
], debug=True)
