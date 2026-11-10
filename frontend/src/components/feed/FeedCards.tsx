import { ACTIVITY_TYPE_META, activityPhase, type ActivityStatus } from "../../types/activities";
import {
  FEED_TASK_PRIORITY_BARS,
  FEED_TASK_STATUS_LABEL,
  type ActivityFeedItem,
  type NewsFeedItem,
  type TaskFeedItem,
  type FeedTaskPriority,
} from "../../types/feed";

function PriorityBars({ priority }: { priority: FeedTaskPriority }) {
  const on = FEED_TASK_PRIORITY_BARS[priority];
  return (
    <span className="feed-prio">
      {[0, 1, 2].map((i) => (
        <i key={i} className={i < on ? "on" : ""} />
      ))}
    </span>
  );
}

function Cover({ url, emoji = "📰" }: { url: string | null; emoji?: string }) {
  return (
    <div
      className="feed-cover"
      style={url ? { backgroundImage: `url(${url})` } : undefined}
    >
      {!url && <span className="feed-cover-emoji">{emoji}</span>}
    </div>
  );
}

export function FeaturedNewsCard({ item, onClick }: { item: NewsFeedItem; onClick: () => void }) {
  return (
    <button type="button" className="feed-featured" onClick={onClick}>
      <Cover url={item.cover_thumbnail_url || item.cover_image_url} />
      <div className="feed-featured-body">
        <span className="badge badge-brand">头条</span>
        <h3>{item.title}</h3>
        {item.summary && <p>{item.summary}</p>}
        <div className="feed-meta">
          <span>👁 {item.views}</span>
        </div>
      </div>
    </button>
  );
}

export function NewsCard({ item, onClick }: { item: NewsFeedItem; onClick: () => void }) {
  return (
    <button type="button" className="feed-cell feed-cell--news" onClick={onClick}>
      <Cover url={item.cover_thumbnail_url || item.cover_image_url} />
      <div className="feed-cell-body">
        <span className="badge badge-brand">新闻</span>
        <h4>{item.title}</h4>
        <div className="feed-meta">
          <span>👁 {item.views}</span>
        </div>
      </div>
    </button>
  );
}

export function ActivityCard({ item, onClick }: { item: ActivityFeedItem; onClick: () => void }) {
  const meta = ACTIVITY_TYPE_META[item.activity_type];
  const phase = activityPhase(item.activity_type, item.status as ActivityStatus);
  return (
    <button type="button" className="feed-cell feed-cell--activity" onClick={onClick}>
      <div className="feed-act-head">
        <span className="badge badge-brand">{meta.label}</span>
        <span className="feed-emoji">{meta.emoji}</span>
      </div>
      <h4>{item.title}</h4>
      <div className="feed-act-foot">
        <span className={"act-medal act-medal--sm " + phase.medalClass}>
          <span className="act-medal-ico">{phase.emoji}</span>
          {phase.label}
        </span>
      </div>
    </button>
  );
}

export function TaskCard({ item, onClick }: { item: TaskFeedItem; onClick: () => void }) {
  return (
    <button type="button" className="feed-cell feed-cell--task" onClick={onClick}>
      <div className="feed-task-head">
        <span className={`feed-status feed-status--${item.status}`}>
          {FEED_TASK_STATUS_LABEL[item.status]}
        </span>
        <PriorityBars priority={item.priority} />
      </div>
      <h4>{item.title}</h4>
      <div className="feed-meta">
        {item.assignee ? `@${item.assignee.nickname || item.assignee.username}` : "未指派"}
      </div>
    </button>
  );
}
