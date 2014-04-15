#!/usr/bin/python

import os, time, base64, argparse
from hashlib import sha256
from . import dbutil
from .abbreviate import abbreviate_space

# glossary:
#  snapshotid: DB id of a given snapshot
#  snapshot: contains data about all children of a rootpath
#  rootpath: e.g. ~ or /Backups/2014-04-15.HHMM
#  localpath: relative to rootpath, e.g. stuff/tahoe/icebackup/setup.py
#  fileid: sha256 of file. Used to spot renames. filecap=captable[fileid]
#  filecap: ?

NON_AGGREGATE, CLOSED_AGGREGATE, OPEN_AGGREGATE = (0,1,2)
LITERAL, SMALL, LARGE = (0,1,2)
# a LITERAL file lives in the filecap itself
# one or more SMALL files live in a single storage object
# a LARGE file is segmented into multiple storage objects

schema = """
CREATE TABLE version -- added in v1
(
 version INTEGER  -- contains one row, set to 1
);

CREATE TABLE `snapshots`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `rootpath` VARCHAR,
 `started` INTEGER, -- timestamp
 `scan_finished` INTEGER, -- timestamp
 `root_id` INTEGER -- dirtable.id
);

CREATE TABLE `dirtable`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `snapshotid` INTEGER,
 `parentid` INTEGER, -- or NULL for a root
 `name` VARCHAR,
 `cumulative_size` INTEGER, -- includes space for the dirnode itself
 `cumulative_items` INTEGER -- includes 1 for the direnode itself
);
CREATE INDEX `dirtable_snapshotid_parentid_name` ON `dirtable`
 (`snapshotid`, `parentid`, `name`);

CREATE TABLE `filetable`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `snapshotid` INTEGER,
 `parentid` INTEGER NOT NULL,
 `name` VARCHAR,
 `size` INTEGER,
 `mtime` INTEGER,
 `fileid` VARCHAR -- hash of file, or random until we want efficient renames
);
CREATE INDEX `filetable_snapshotid_parentid_name` ON `filetable`
 (`snapshotid`, `parentid`, `name`);
CREATE INDEX `filetable_fileid` ON `filetable` (`fileid`);

CREATE TABLE `need_to_hash`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `filetable_id` INTEGER, -- filetable row to update with fileid
 `localpath` VARCHAR,
 `mtime` INTEGER
);

CREATE TABLE `need_to_upload`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `path` VARCHAR, -- absolute path, not localpath
 `fileid` VARCHAR UNIQUE, -- set captable[fileid]=filecap when uploaded
 `size` INTEGER
);
CREATE INDEX `need_to_upload_fileid` ON `need_to_upload` (`fileid`);

CREATE TABLE `upload_schedule`
-- one row per stored object (either aggregate, one-file, or segment-of-file)
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `storage_index` VARCHAR, -- filled in when we're done
 `aggregate` INTEGER
 -- aggregate=0 (NON_AGGREGATE), 1 (CLOSED_AGGREGATE), 2 (OPEN_AGGREGATE)
);
CREATE INDEX `upload_schedule_aggregate` ON `upload_schedule` (`aggregate`);

CREATE TABLE `upload_schedule_files`
(
 `upload_schedule_id` INTEGER,
 `filenum` INTEGER,
 `size` INTEGER, -- size of this part
 `path` VARCHAR, -- what gets uploaded here
 `offset` INTEGER -- what part of 'path' gets uploaded
);
CREATE UNIQUE INDEX `upload_schedule_files_id` ON `upload_schedule_files` (`upload_schedule_id`, `filenum`);



CREATE TABLE `captable`
(
 `fileid` VARCHAR PRIMARY KEY,
 `type` INTEGER, -- 0:lit, 1:small, 2:big
 `filecap` VARCHAR
);

CREATE INDEX `captable_filecap` ON `captable` (`filecap`);

CREATE TABLE `small_objmap`
(
 `filecap` VARCHAR PRIMARY KEY,
 `storage_index` VARCHAR,
 `offset` INTEGER,
 `size` INTEGER,
 `file_enckey` VARCHAR,
 `cthash` VARCHAR
);

CREATE TABLE `big_objmap`
(
 `filecap` VARCHAR PRIMARY KEY,
 `file_enckey` VARCHAR,
 `cthash` VARCHAR
);

CREATE TABLE `big_objmap_segments`
(
 `filecap` VARCHAR PRIMARY KEY,
 `segnum` INTEGER,
 `storage_index` VARCHAR
);

"""

class Aggregator:
    """I keep track of which scheduled-upload-object is available to hold
    aggregates of small files.

    Any row in 'upload_schedule' that has aggregate=2 is available to
    house aggregate objects. For now, we only keep one of these around. (in
    the future, we might have multiple ones, to make it easier to keep
    spatially-related files in the same aggregate).
    """

    def __init__(self, db, MAXCHUNK):
        self.db = db
        self.MAXCHUNK = MAXCHUNK
        self.upid = None

    def get_upid(self):
        if self.upid is None:
            row = self.db.execute(
                "SELECT * FROM upload_schedule"
                " WHERE aggregate=?"
                " LIMIT 1", (OPEN_AGGREGATE,)
                ).fetchone()
            if row:
                self.upid = row["id"]
                self.size = self.db.execute(
                    "SELECT SUM(size)"
                    " FROM upload_schedule_files"
                    " WHERE upload_schedule_id=?",
                    (self.upid,)).fetchone()[0]
                row = self.db.execute(
                    "SELECT MAX(filenum) FROM upload_schedule_files"
                    " WHERE upload_schedule_id=?",
                    (self.upid,)).fetchone()
                # returns (None,) if the table was empty
                if row[0] is None:
                    self.next_filenum = 0
                else:
                    self.next_filenum = row[0] + 1
        if self.upid is None:
            self.upid = self.db.execute(
                "INSERT INTO upload_schedule"
                " (aggregate) VALUES (?)", (OPEN_AGGREGATE,)
                ).lastrowid
            self.size = 0
            self.next_filenum = 0
        return self.upid, self.next_filenum

    def add(self, size):
        self.size += size
        self.next_filenum += 1
        if self.size > self.MAXCHUNK:
            self.close()

    def close(self):
        if not self.upid:
            return
        self.db.execute("UPDATE upload_schedule"
                        " SET aggregate=?"
                        " WHERE id=?", (CLOSED_AGGREGATE, self.upid,))
        self.upid = None


class Scanner:
    MINCHUNK = 1*1000*1000
    MAXCHUNK = 100*1000*1000

    def __init__(self, rootpath, dbfile, reporter=None):
        assert isinstance(rootpath, unicode)
        self.rootpath = os.path.abspath(rootpath)
        self.dbfile = dbfile
        self.reporter = reporter
        self._last_reported = 0
        self.db = dbutil.get_db(dbfile, create_version=(schema, 1),
                                synchronous="OFF")
        self.prev_snapshotid, self.prev_rootid = None, None
        row = self.db.execute("SELECT * FROM snapshots"
                              " WHERE scan_finished IS NOT NULL"
                              " ORDER BY scan_finished DESC LIMIT 1").fetchone()
        if row:
            self.prev_snapshotid = row["id"]
            self.prev_rootid = row["root_id"]
        print "PREV_SNAPSHOTID", self.prev_snapshotid

    def report(self, *args, **kwargs):
        now = time.time()
        if now - self._last_reported < 0.010:
            return
        self._last_reported = now
        # at most one event every 10ms
        if self.reporter:
            self.reporter(*args, **kwargs)

    def scan(self):
        started = time.time()
        snapshotid = self.db.execute("INSERT INTO snapshots"
                                     " (started) VALUES (?)",
                                     (started,)).lastrowid
        self._dirpath = [{"name": u"."}]
        (rootid, cumulative_size, cumulative_items) = \
              self.process_directory(snapshotid, u".", None, self.prev_rootid)
        scan_finished = time.time()
        self.db.execute("UPDATE snapshots"
                        " SET scan_finished=?, rootpath=?, root_id=?"
                        " WHERE id=?",
                        (scan_finished, self.rootpath, rootid,
                         snapshotid))
        self.db.commit()
        self.report("scan complete",
                    size=cumulative_size, items=cumulative_items)
        return (cumulative_size, cumulative_items)

    def process_directory(self, snapshotid, localpath, parentid, prevnode):
        assert isinstance(localpath, unicode)
        # localpath is relative to self.rootpath
        abspath = os.path.join(self.rootpath, localpath)
        #print "%sDIR: %s" % (" "*(len(localpath.split(os.sep))-1), localpath)
        self.report("entering directory", self._dirpath)
        s = os.stat(abspath)
        size = s.st_size # good enough for now
        name = os.path.basename(os.path.abspath(abspath))
        dirid = self.db.execute(
            "INSERT INTO dirtable"
            " (snapshotid, parentid, name)"
            " VALUES (?,?,?)",
            (snapshotid, parentid, name)
            ).lastrowid
        cumulative_size = size
        cumulative_items = 1
        children = os.listdir(abspath)
        self._dirpath[-1]["num_children"] = len(children)
        for i,child in enumerate(children):
            childpath = os.path.join(localpath, child)
            abschildpath = os.path.join(self.rootpath, childpath)

            if os.path.isdir(abschildpath):
                row = self.db.execute(
                    "SELECT * FROM dirtable"
                    " WHERE snapshotid=? AND parentid=? AND name=?",
                    (self.prev_snapshotid, prevnode, child)).fetchone()
                prevchildnode = row["id"] if row else None
                self._dirpath.append({"name": child, "num": i})
                try:
                    new_dirid, subtree_size, subtree_items = \
                               self.process_directory(snapshotid,
                                                      childpath, dirid,
                                                      prevchildnode)
                    cumulative_size += subtree_size
                    cumulative_items += subtree_items
                except OSError as e:
                    print e
                    self._dirpath.pop()
                    continue
                self._dirpath.pop()
            elif os.path.isfile(abschildpath):
                row = self.db.execute(
                    "SELECT * FROM filetable"
                    " WHERE snapshotid=? AND parentid=? AND name=?",
                    (self.prev_snapshotid, prevnode, child)).fetchone()
                prevchildnode = row["id"] if row else None
                self.report(" processing file", self._dirpath, name=child, i=i)
                file_size = self.process_file(snapshotid,
                                              childpath, dirid,
                                              prevchildnode)
                cumulative_size += file_size
                cumulative_items += 1
            elif os.path.islink(abschildpath):
                pass
            else:
                print "ignoring non-file/dir/link %s" % abschildpath

        self.db.execute("UPDATE dirtable"
                        " SET cumulative_size=?, cumulative_items=?"
                        " WHERE id=?",
                        (cumulative_size, cumulative_items,
                         dirid))
        self.report("exiting directory", self._dirpath)
        return dirid, cumulative_size, cumulative_items

    def process_file(self, snapshotid, localpath, parentid, prevnodeid):
        assert isinstance(localpath, unicode)
        abspath = os.path.join(self.rootpath, localpath)
        name = os.path.basename(os.path.abspath(abspath))
        #print "%sFILE %s" % (" "*(len(localpath.split(os.sep))-1), name)

        s = os.stat(abspath)
        size = s.st_size
        ftid = self.db.execute("INSERT INTO filetable"
                               " (snapshotid, parentid, name,"
                               "  size, mtime)"
                               " VALUES (?,?,?, ?,?)",
                               (snapshotid, parentid, name,
                                s.st_size, s.st_mtime)
                               ).lastrowid

        # if the file looks old (the previous snapshot had a file with the
        # same path, size, and mtime), then we're allowed to assume it hasn't
        # changed, and copy the fileid from the last snapshot
        prevnode = None
        if prevnodeid:
            prevnode = self.db.execute(
                "SELECT * FROM filetable WHERE id=?",
                (prevnodeid,)).fetchone()
        if (prevnode and
            prevnode["size"] == size and
            prevnode["mtime"] == s.st_mtime):
            self.db.execute("UPDATE filetable SET fileid=? WHERE id=?",
                            (prevnode["fileid"], ftid))
        else:
            # otherwise, schedule it for hashing, which will produce the
            # fileid. If that fileid is not one we've previously uploaded,
            # we'll schedule it for uploading.
            self.db.execute("INSERT INTO need_to_hash"
                            " (filetable_id, localpath, mtime)"
                            " VALUES (?,?,?)",
                            (ftid, localpath, s.st_mtime))

        return size

    # after scan() (process_directory/process_file) completes, the
    # 'snapshots' row will be done (scan_finished!=NULL), and the dirtable
    # will be complete (all data in all rows will be present). The filetable
    # will contain all rows, however:
    #
    #  * some rows will not have a fileid. These rows should each have a
    #    matching entry in 'need_to_hash'. Each represents a new file or a
    #    file which does not match the size/mtime of the previous scan.

    def hash_files(self):
        count = self.db.execute("SELECT COUNT(*) FROM need_to_hash").fetchone()[0]
        print "need_to_hash: %d" % count
        while True:
            next_batch = list(self.db.execute("SELECT * FROM need_to_hash"
                                              " ORDER BY id ASC"
                                              " LIMIT 200").fetchall())
            if not next_batch:
                break
            for row in next_batch:
                #print row["localpath"].encode("utf-8")
                self.hash_file(row)
            where_clause = " OR ".join(["id=?" for row in next_batch])
            values = tuple([row["id"] for row in next_batch])
            self.db.execute("DELETE FROM need_to_hash WHERE %s" % where_clause,
                            values)
            self.db.commit()
        count = self.db.execute("SELECT COUNT(*) FROM need_to_upload").fetchone()[0]
        print "need_to_upload: %d" % count

    def hash_file(self, row):
        size = self.db.execute("SELECT size FROM filetable WHERE id=?",
                               (row["filetable_id"],)
                               ).fetchone()["size"]
        fileid = self.hash_fileid(row["localpath"], row["mtime"], size)
        self.db.execute("UPDATE filetable SET fileid=? WHERE id=?",
                        (row["filetable_id"], fileid))

        uploaded = self.db.execute("SELECT * FROM captable"
                                   " WHERE fileid=?",
                                   (fileid,)
                                   ).fetchone()
        if uploaded:
            return

        already_marked = self.db.execute("SELECT *"
                                         " FROM need_to_upload"
                                         " WHERE fileid=?",
                                         (fileid,)).fetchone()
        if already_marked:
            return

        #print " need to upload"
        path = os.path.join(self.rootpath, row["localpath"])
        self.db.execute("INSERT INTO need_to_upload"
                        " (path, fileid, size)"
                        " VALUES (?,?,?)",
                        (path, fileid, size))

    def hash_fileid(self, localpath, mtime, size):
        # fileid will be the raw sha256 hash of the file contents. Hashing
        # files will let us efficiently handle renames (not re-uploading an
        # unmodified file that just happens to live in a different location
        # than before) as well as duplicates. We'll only hash files when we
        # don't recognize their path+mtime+size. For now, rather than pay the
        # IO cost of hashing such files, we'll just make the fileid a
        # deterministic random function of path+mtime+size.
        fileid = sha256("%s:%s:%s" % (localpath.encode("utf-8"), mtime, size)).hexdigest()
        return fileid

    # after hash_files(), all filetable rows should have a fileid. However,
    # some of these fileids will not be present in 'captable'. These files
    # need to be uploaded, and will match entries in 'need_to_upload'.

    def schedule_uploads(self):
        # the actual upload algorithm will batch together small files, and
        # split large ones. For now, we just pretend.
        DBX = self.db.execute
        count = DBX("SELECT COUNT(*) FROM need_to_upload").fetchone()[0]
        print "need_to_upload: %d" % count
        # begin transaction
        agg = Aggregator(self.db, self.MAXCHUNK)
        for row in DBX("SELECT * FROM need_to_upload ORDER BY id ASC"):
            size = row["size"]
            if size < 144: # LIT
                filecap = "LIT:fake" # todo: base64-encode the contents
                DBX("INSERT INTO captable (fileid, type, filecap)"
                    " VALUES (?,?,?)",
                    (row["fileid"], LITERAL, filecap))
            elif size < self.MINCHUNK: # small, so aggregate
                # the Aggregator adds rows to 'upload_schedule', but we add
                # rows to 'upload_schedule_files' here
                upid, filenum = agg.get_upid()
                DBX("INSERT INTO upload_schedule_files"
                    " (upload_schedule_id, filenum, size,"
                    "  path, offset)"
                    " VALUES (?,?,?, ?,?)",
                    (upid, filenum, size,
                     row["path"], 0))
                agg.add(size)
            else: # large, not aggregated
                # either one segment, or split into multiple segments
                #print "large file", size
                for filenum,offset in enumerate(range(0, size, self.MAXCHUNK)):
                    length = min(size - offset, self.MAXCHUNK)
                    #print " adding", offset, length, "as filenum", filenum
                    upid = DBX("INSERT INTO upload_schedule"
                               " (aggregate) VALUES (?)", (NON_AGGREGATE,)
                               ).lastrowid
                    DBX("INSERT INTO upload_schedule_files"
                        " (upload_schedule_id, filenum, size,"
                        "  path, offset)"
                        " VALUES (?,?,?, ?,?)",
                        (upid, filenum, length,
                         row["path"], offset))
        agg.close()
        # end transaction
        DBX("DELETE FROM need_to_upload")
        self.db.commit()
        count = DBX("SELECT COUNT(*) FROM upload_schedule").fetchone()[0]
        aggregate_count = DBX("SELECT COUNT(*) FROM upload_schedule"
                              " WHERE aggregate=?",
                              (CLOSED_AGGREGATE,)).fetchone()[0]
        print "upload objects: %d (of which %d hold aggregates)" \
              % (count, aggregate_count)

    # after schedule_uploads(), 'need_to_upload' will be empty, and
    # 'upload_schedule'/'upload_schedule'files' will be populated with the
    # mappings from local files to storage objects (many-to-one for small
    # files that get aggregated together, one-to-one for medium-sized files,
    # and one-to-many for large files that must be segmented before upload).

    def upload_files(self):
        DBX = self.db.execute
        count = DBX("SELECT COUNT(*) FROM upload_schedule").fetchone()[0]
        print "uploads scheduled: %d" % count
        while True:
            next_batch = list(DBX("SELECT * FROM upload_schedule"
                                  " ORDER BY id ASC"
                                  " LIMIT 20").fetchall())
            if not next_batch:
                break
            for row in next_batch:
                # fake it
                upid = row["id"]
                objectpath, size = self.prepare_upload(upid)
                objectcap = self.upload_object(objectpath, size)
                # TODO: store it somewhere, update some stuff
                DBX("DELETE FROM upload_schedule WHERE id=?", (upid,))
                DBX("DELETE FROM upload_schedule_files WHERE upload_schedule_id=?", (upid,))
        self.db.commit()
        print "done"

    def prepare_upload(self, upid):
        DBX = self.db.execute
        size = DBX("SELECT SUM(size) FROM upload_schedule_files"
                   " WHERE upload_schedule_id=?", (upid,)
                   ).fetchone()[0]
        return "path", size

    def upload_object(self, objectpath, size):
        print "fake-uploading %d bytes" % size
        storage_index = base64.b64encode(os.urandom(32))
        objectcap = "fake:"+storage_index
        return objectcap

    def upload_file(self, abspath):
        return "fake filecap"
        f = open(abspath, "rb")
        h = sha256()
        while True:
            data = f.read(32*1024)
            if not data:
                break
            h.update(data)
        f.close()
        filecap = "file:%s" % h.hexdigest()
        return filecap

    # after upload_files(), 'upload_schedule' will be empty, and all fileids
    # in 'filetable' should have filecaps in 'captable'.

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dbname")
    ap.add_argument("root")
    ap.add_argument("command")
    args = ap.parse_args()
    dbname = args.dbname
    assert dbname.endswith(".sqlite"), dbname
    root = args.root.decode("utf-8")
    assert os.path.isdir(root), root
    s = Scanner(root, dbname)
    command = args.command
    if command == "scan":
        cumulative_size, cumulative_items = s.scan()
        print "cumulative_size %d (%s)" % (cumulative_size,
                                           abbreviate_space(cumulative_size))
        print "cumulative_items %d" % cumulative_items
    elif command == "hash_files":
        s.hash_files()
    elif command == "schedule_uploads":
        s.schedule_uploads()
    elif command == "upload":
        s.upload_files()
    else:
        print "unknown command", command

if __name__ == "__main__":
    main()
