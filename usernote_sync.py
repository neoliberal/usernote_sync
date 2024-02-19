"""Macros and toolbox integration for moderation"""

from base64 import b64decode
import json
import os
import sys
import time
from zlib import decompress

import praw
import prawcore

import slack_python_logging


# Translate modtoolbox note labels to new reddit labels
label_translation = {
    "gooduser": "HELPFUL_USER",
    "spamwatch": "SPAM_WATCH",
    "spamwarn": "SPAM_WARNING",
    "abusewarn": "ABUSE_WARNING",
    "ban": "BAN",
    "permban": "PERMA_BAN",
}


class UsernoteSync:
    """Main bot class"""

    def __init__(self):
        """Initialize class, requires appropriate environment variables"""
        self.reddit = praw.Reddit(
            client_id = os.environ["client_id"],
            client_secret = os.environ["client_secret"],
            refresh_token = os.environ["refresh_token"],
            user_agent = "linux:fashbot:v0.1 (by /u/jenbanim)"
        )
        self.subreddit = self.reddit.subreddit(os.environ["subreddit"])
        self.logger = slack_python_logging.getLogger(
            app_name = "fashbot",
            stream_loglevel = "DEBUG",
            slack_loglevel = "CRITICAL"
        )
        self.start_time = time.time()


    def get_usernotes(self, after_epoch = 0):
        """Load and format a user's notes from subreddit wiki"""
        usernotes = json.loads(self.subreddit.wiki["usernotes"].content_md)
        constants = usernotes["constants"]
        notes = json.loads(
            decompress(b64decode(usernotes["blob"])).decode("utf-8")
        )
        new_notes = []
        for user in notes:
            for note in notes[user]["ns"]:
                # Build new note
                note_author = constants["users"][note["m"]]
                if note["t"] < after_epoch:
                    # Disregard notes from before after_epoch
                    continue
                note_time = time.strftime(
                    "%Y-%m-%d",
                    time.localtime(note["t"])
                )
                note_text = note["n"]
                new_note_text = f"{note_time} | {note_author} | {note_text}"
                # Build new label
                note_label = constants["warnings"][note["w"]]
                new_note_label = label_translation.get(note_label, None)
                # Build thing
                note_link_split = note["l"].split(",")
                if len(note_link_split) == 1:
                    # No link
                    new_thing = None
                if len(note_link_split) == 2:
                    # Submission link
                    submission_id = note_link_split[1]
                    new_thing = self.reddit.submission(submission_id)
                if len(note_link_split) == 3:
                    # Comment link
                    comment_id = note_link_split[2]
                    new_thing = self.reddit.comment(comment_id)
                new_notes.append({
                    "label": new_note_label,
                    "note": new_note_text[:250],
                    "redditor": self.reddit.redditor(user),
                    "subreddit": self.subreddit,
                    #"thing": new_thing
                    "thing": None
                })
        return new_notes

    
    def upload_notes(self, new_notes):
        while new_notes:
            for note in new_notes:
                print(f"{len(new_notes)} remaining")
                try:
                    time.sleep(1)
                    self.reddit.notes.create(**note)
                    new_notes.remove(note)
                except prawcore.exceptions.TooManyRequests:
                    # I hate the API. I hate the API. I hate the API.
                    time.sleep(5)
                except praw.exceptions.RedditAPIException:
                    # Account deleted or suspended
                    new_notes.remove(note)
    

    def delete_notes(self, new_notes):
        # Deletes notes from subreddit using the users in the new_notes list
        # Intended as an undo action in case something goes wrong
        users = list(set([note["redditor"].name for note in new_notes]))
        me = self.reddit.user.me()
        while users:
            for user in users:
                try:
                    for note in self.subreddit.mod.notes.redditors(user, limit=None):
                        if note.type != "NOTE":
                            continue
                        if note.moderator != me:
                            continue
                        note.delete()
                    users.remove(user)
                except prawcore.exceptions.TooManyRequests:
                    time.sleep(5)
                except praw.exceptions.RedditAPIException:
                    # Account deleted or suspended
                    users.remove(user)


if __name__ == "__main__":
    """Main program loop. Create a UsernoteSync instance and listen continuously."""

    usernote_sync = UsernoteSync()

    # Log uncaught exceptions to Slack before exiting
    def log_excepthook(ex_type, ex_value, ex_traceback):
        fashbot.logger.critical(
            "Critical Exception caught, exiting",
            exc_info=(ex_type, ex_value, ex_traceback)
        )
    sys.excepthook = log_excepthook # Wish I could use a lambda :/

    after_epoch = time.time() # First run will be useless, but whateva
    while True:
        new_usernotes = fashbot.get_usernotes(after_epoch = after_epoch)
        fashbot.upload_notes(new_usernotes)
        after_epoch = time.time() # set for our next run
        time.sleep(60)
