X = log idx during snap
snapshot.X.bin
after snap is opened, each line is written to the DB one by one.
snap line = k5 v31
new_snap is a 2D string array in memory
entry = KV pair in DB
snap.X.file is on disk

each entry is written to <mark style="background: #FFB8EBA6;">buffer</mark> ONE BY ONE
all entries are flushed to disk TOGETHER
buffer periodically <mark style="background: #FFB8EBA6;">auto flushes</mark> entries to disk

# <span style="color:rgb(0, 176, 240)">AUTO FLUSH CRASH BUG</span>
1. take_pics() is halfway done writing entries from new_snap into buffer
2. take_pics() wants to write k5 v31 to the buffer
3. take_pics() writes k5 v3 into the buffer
4. buffer auto flushes k5 v3 into snap.203 file in disk (AUTO FLUSH CUT OFF)
	1. node ==does NOT== crash
		1. node writes 1 to buffer and continues writing entries
		2. The next auto flush magically adds 1 to k5 v3 making the correct entry of k5 v31
	2. node ==does== crash
		1. load_snap() pulls snap.203 from disk
		2. load_snap() copies entries from snap to DB including k5 v3
		3. replay_wal() starts replaying entries from idx=204
			1.<span style="color:rgb(192, 0, 0)"><span style="color:rgb(192, 0, 0)"> <span style="color:rgb(0, 0, 0)">DB has invalid entry</span></span></span>


If auto flush cuts off entry, then the next flush magically fixes it.
If auto flush cuts off entry, and the node crashes, then there is no next flush to magically fix it.

The solution is to write to snap.203.temp instead of snap.203.bin. Then, rename snap.203.temp to snap.203.bin.
load_snap() only loads snaps with the .bin extension!
If the node does crash after auto flush cuts off an entry, then load_snap() would load snap.103.bin
cluster processes writes in agreed upon order via SNS+SQS
shadow node is not apart of the cluster and does not participate in chaos testing
temp files would only persist in the snapshot directory in the event of a crash because otherwise they would be renamed to .bin

all entries after the AUTO FLUSH CRASH are either AUTO FLUSH CUT OFF entries or UNWRITTEN entries

Potential Research Idea
* create a shadow node that polls from SNS+SQS
* ==diff== temp snaps to the shadow snaps to get a list of all AUTO FLUSH CUT OFF entries


