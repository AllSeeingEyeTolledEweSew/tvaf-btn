# FAQ

## What is tvaf?

tvaf is a BitTorrent client that provides browsing and streaming data from
private trackers. It is written in Python and based on [rasterbar's
libtorrent](https://libtorrent.org).

tvaf runs headlessly. It participates in the BitTorrent protocol, and you
access data from tvaf over other protocols like HTTP or SFTP.

tvaf is aware of private tracker seeding requirements and incentives. It
provides a configurable system to automatically delete torrents when you run
out of disk space.

tvaf's data management goals are:
1. Only download data that's actively being used, or for seeding requirements.
1. Only delete data when necessary, and then only the least-useful data.

__tvaf's goal is to maximize your ratio with no effort from you.__ tvaf puts
strong emphasis on being a good BitTorrent citizen, which overlaps with this
goal.

tvaf is designed to be shared. You can grant access to users to stream data
on-demand, up to a configurable quota. Users can't impersonate the
administrator to the tracker, or see the passkey. Administrators are still
responsible for their ratio, so only share access with people you trust!

## How is tvaf better than CouchPotato, etc?

CouchPotato and its cousins automatically download content when it becomes
available. Other projects such as Plex Requests let users request to
download arbitrary content.

tvaf has two main advantages over auto-downloaders:
1. tvaf streams content on-demand, so it eliminates download times.
1. tvaf makes it much easier to decide what content to keep on your disk. As
   far as I know, no auto-downloader has an integrated way to automatically
   delete content that is no longer needed. tvaf can do this!

## Will tvaf destroy my ratio?

No. It remains to be proven, but I claim that using tvaf will _improve_ your
ratio versus not using tvaf.

If you need to fully download a movie before you can watch it, you'll find
yourself downloading movies to "watch later", but never getting around to it.
That download was wasted! If you use Plex Requests (or something similar), you
may notice users do this much more when they're not ultimately responsible for
your ratio, or managing your hard drive space!

With tvaf, you only download data you are using in real-time. This alone
improves your ratio.

And it gets better. Now that you're dedicating less of your disk space to
"watch later" movies, you can use that space for other stuff. tvaf will use
that space to keep content with fewer seeders. That leads to more upload, which
leads to a better ratio!

Best of all, tvaf automates this space management, so you never have to worry
about getting it right.

That said, a malicious user could continuously churn through their quota with
wasted downloads. You should only share access with users you trust!

## Isn't tvaf just Popcorn Time?

In many ways, yes. tvaf was indeed inspired by Popcorn Time.

I contend that [Popcorn Time would be better if it was
headless](#why-is-tvaf-headless), and may cause [sequential downloading
problems](#isnt-sequential-downloading-bad) due to using [public trackers
instead of private ones](#why-only-private-trackers).

Popcorn Time, and its various incarnations and cousins, are not good BitTorrent
citizens in their default configuration. Many of them delete their data when
you close them. tvaf wants to keep uploading!

## Why is tvaf headless?

Many on-demand streaming programs like Popcorn Time have a GUI with a video
player. They run a BitTorrent client on user's desktop or laptop. Sometimes,
the BitTorrent client runs as JavaScript in your browser.

tvaf is designed to run headlessly on your NAS or seedbox.

This is because tvaf puts strong emphasis on the _sharing and uploading_ parts
of BitTorrent. This works best with a large disk, robust network connection,
and an always-on computer. Most end-user machines have none of these!

tvaf wants to be a good BitTorrent citizen, and it's too easy to be a bad
citizen when running on an end-user machine.

## Isn't sequential downloading bad?

__TL;DR__: Not on private trackers.

There's an argument that [sequential downloading is
bad](https://wiki.vuze.com/w/Sequential_downloading_is_bad) in BitTorrent. tvaf
mostly does sequential downloading, to stream content. Is tvaf bad?

I argue that sequential downloading is not bad on private trackers, because
peers behave differently than in "public" torrent swarms.

On "public" swarms, peers are incentivized with a "tit for tat" model. They
quit after doing their "fair share" of seeding to a 1.0 ratio.

On private trackers, peers are incentivized through ratio requirements or
prestige to seed the rarest content possible for as long as possible.

This means that peers will always be interested in each other, so long as any
exchange is possible, and there is minimal likelihood that seeders of rare
content will quit. They would be even less likely to quit if they are using
tvaf for fully automated management!

This behavior does not produce interest cliques or seed starvation, two of the
common criticisms of sequential downloading.

That said, streaming BitTorrent data does induce a constant endgame. tvaf will
issue duplicate piece requests to multiple peers if one is taking too long,
which can lead to wasted data transfer. The amount of waste should be small, as
fast peers become preferred over slow ones.

## Why only private trackers?

tvaf only supports private trackers right now, mainly because [sequential
downloading on private trackers isn't bad](#isnt-sequential-downloading-bad).

Private trackers provide wonderful libraries of metadata about content. tvaf
makes a very good browser for this content.

BitTorrent is also tvaf's protocol of choice because BitTorrent naturally
allows random access to data. Random access means tvaf can be used for any
type of data, even software or games.

## Does tvaf break tracker rules about sharing accounts?

No. Tracker accounts are not shared. tvaf users have no access to tracker
account credentials, passkeys, or other secrets. tvaf users can't act on behalf
of a tracker account. The only thing they can do is request to download data.

You can think of tvaf as an on-demand version of Plex Requests.

## Why does tvaf cache so much?

tvaf caches enough data to allow browsing the entire library of a private
tracker.

In practice, this means tvaf must maintain a local cache of pretty much all
metadata available on that tracker.

Private trackers strictly limit the number of API calls you can make. If tvaf
cached nothing, it would need to call an API every time a user browses a
directory. Then we would run the risk of running over our call limit, and
telling ALL users they need to wait minutes or hours before using tvaf!

## Why yet another BitTorrent client?

Private trackers only want to allow proven, secure BitTorrent clients. Why did
we write yet another client, instead of creating some plugin for an established
one?

Over tvaf's long development history, we saw that tvaf's functionality would
require many changes to the core code of existing clients. We did try to make
these changes, but had very little success getting them accepted.

I believe this is partly because BitTorrent developers widely hold the belief
that [sequential downloading is bad](#isnt-sequential-downloading-bad) even
when it's not, and many do not hold private trackers in high regard.

So we have a chicken-and-egg problem: we can't prove tvaf's functionality,
because private trackers only want to whitelist proven clients; and we can't
integrate tvaf into an existing client because it's unproven.

On top of this, tvaf works best when it's in control of torrents being added
and deleted. If tvaf were a plugin, it could get "out of sync" with its torrent
client. I pursued many designs to try to work around this but every design was
quite brittle.

I believe writing a standalone tvaf client was the only way out of this puzzle,
despite the challenge of convincing each private tracker to accept a new
client. In the future, I hope tvaf's success will mean that more mainstream
clients adopt its functionality directly.
