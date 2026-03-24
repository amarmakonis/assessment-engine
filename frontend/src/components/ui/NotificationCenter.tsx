import React, { useState, useEffect } from 'react';
import { Bell, CheckCircle, XCircle, Info } from 'lucide-react';
import { batchAPI } from '../../services/api';
import { clsx } from 'clsx';
import { formatDistanceToNow } from 'date-fns';

export const NotificationCenter: React.FC = () => {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  const fetchNotifications = async () => {
    try {
      const data = await batchAPI.getNotifications();
      setNotifications(data.items);
      setUnreadCount(data.items.filter((n: any) => !n.read).length);
    } catch (err) {
      console.error('Failed to fetch notifications', err);
    }
  };

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 10000); // Poll every 10s
    return () => clearInterval(interval);
  }, []);

  const handleMarkRead = async () => {
    try {
      await batchAPI.markNotificationsRead();
      setUnreadCount(0);
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    } catch (err) {
      console.error('Failed to mark notifications read', err);
    }
  };

  const toggleOpen = () => {
    setIsOpen(!isOpen);
    if (!isOpen && unreadCount > 0) {
      handleMarkRead();
    }
  };

  const getIcon = (type: string) => {
    switch (type) {
      case 'SUCCESS': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'ERROR': return <XCircle className="w-4 h-4 text-red-500" />;
      default: return <Info className="w-4 h-4 text-blue-500" />;
    }
  };

  return (
    <div className="relative">
      <button 
        onClick={toggleOpen}
        className="p-2 text-slate-400 hover:text-white transition-colors relative"
      >
        <Bell className="w-6 h-6" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[10px] flex items-center justify-center rounded-full animate-pulse">
            {unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 overflow-hidden ring-1 ring-white/10 glassmorphism">
          <div className="p-4 border-b border-slate-700 flex justify-between items-center bg-white/5">
            <h3 className="font-semibold text-white">Notifications</h3>
            {unreadCount > 0 && (
              <button 
                onClick={handleMarkRead}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="p-8 text-center text-slate-500 italic text-sm">
                No notifications yet
              </div>
            ) : (
              notifications.map((notif) => (
                <div 
                  key={notif._id || notif.id}
                  className={clsx(
                    "p-4 border-b border-slate-800 hover:bg-white/5 transition-colors cursor-default",
                    !notif.read && "bg-white/[0.02]"
                  )}
                >
                  <div className="flex gap-3">
                    <div className="mt-1">{getIcon(notif.type)}</div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-200 leading-tight">
                        {notif.message}
                      </p>
                      <span className="text-[10px] text-slate-500 mt-1 block">
                        {formatDistanceToNow(new Date(notif.createdAt))} ago
                      </span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
