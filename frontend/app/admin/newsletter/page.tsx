'use client';

import { useState, useEffect } from 'react';
import { 
  Users, 
  Mail, 
  Download, 
  Search, 
  Trash2, 
  MoreVertical,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Send
} from 'lucide-react';

interface Subscriber {
  id: string;
  email: string;
  created_at: string;
  status: 'active' | 'unsubscribed';
  source: string;
}

export default function NewsletterAdmin() {
  const [subscribers, setSubscribers] = useState<Subscriber[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchSubscribers = async () => {
    setLoading(true);
    try {
      // In a real app, you'd fetch from an API route
      // For now, I'll use the supabase client directly for convenience in admin
      const { supabase } = await import('@/lib/supabase');
      const { data, error } = await supabase
        .from('subscribers')
        .select('*')
        .order('created_at', { ascending: false });

      if (error) throw error;
      setSubscribers(data || []);
    } catch (error) {
      console.error('Failed to fetch subscribers:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSubscribers();
  }, []);

  const filteredSubscribers = subscribers.filter(s => 
    s.email.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-[#0f1115] text-white p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-end mb-8">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-orange-400 to-amber-200 bg-clip-text text-transparent mb-2">
              Newsletter Management
            </h1>
            <p className="text-gray-600">Manage your audience and send updates</p>
          </div>
          <div className="flex gap-4">
            <button className="flex items-center gap-2 px-6 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-xl transition-all shadow-lg shadow-orange-500/20">
              <Send className="w-4 h-4" />
              New Broadcast
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-2">
              <div className="p-3 bg-blue-500/10 rounded-xl">
                <Users className="w-6 h-6 text-blue-400" />
              </div>
              <h3 className="text-gray-600 font-medium">Total Subscribers</h3>
            </div>
            <p className="text-3xl font-bold">{subscribers.length}</p>
          </div>
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-2">
              <div className="p-3 bg-green-500/10 rounded-xl">
                <CheckCircle2 className="w-6 h-6 text-green-400" />
              </div>
              <h3 className="text-gray-600 font-medium">Active</h3>
            </div>
            <p className="text-3xl font-bold">{subscribers.filter(s => s.status === 'active').length}</p>
          </div>
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-2">
              <div className="p-3 bg-orange-500/10 rounded-xl">
                <Mail className="w-6 h-6 text-orange-400" />
              </div>
              <h3 className="text-gray-600 font-medium">Growth (30d)</h3>
            </div>
            <p className="text-3xl font-bold">+12%</p>
          </div>
        </div>

        {/* List Controls */}
        <div className="flex gap-4 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input 
              type="text"
              placeholder="Search by email..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-12 pr-4 py-3 bg-[#1a1d23] border border-white/10 rounded-xl focus:border-orange-500/50 outline-none transition-all"
            />
          </div>
          <button 
            onClick={fetchSubscribers}
            className="p-3 bg-[#1a1d23] border border-white/10 rounded-xl hover:bg-white/5 transition-all"
          >
            <RefreshCw className={`w-5 h-5 text-gray-600 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button className="flex items-center gap-2 px-6 py-3 bg-[#1a1d23] border border-white/10 rounded-xl hover:bg-white/5 transition-all text-gray-600">
            <Download className="w-4 h-4" />
            Export CSV
          </button>
        </div>

        {/* Subscribers Table */}
        <div className="bg-[#1a1d23] rounded-2xl border border-white/5 overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/5 bg-white/[0.02]">
                <th className="px-6 py-4 text-sm font-semibold text-gray-600">Subscriber</th>
                <th className="px-6 py-4 text-sm font-semibold text-gray-600">Date Joined</th>
                <th className="px-6 py-4 text-sm font-semibold text-gray-600">Source</th>
                <th className="px-6 py-4 text-sm font-semibold text-gray-600">Status</th>
                <th className="px-6 py-4 text-sm font-semibold text-gray-600 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                [1,2,3,4,5].map(i => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={5} className="px-6 py-8">
                      <div className="h-4 bg-white/5 rounded-full w-full"></div>
                    </td>
                  </tr>
                ))
              ) : filteredSubscribers.length > 0 ? (
                filteredSubscribers.map((sub) => (
                  <tr key={sub.id} className="hover:bg-white/[0.01] transition-colors group">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-orange-500/10 flex items-center justify-center text-orange-500 text-xs font-bold uppercase">
                          {sub.email.charAt(0)}
                        </div>
                        <span className="font-medium">{sub.email}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {new Date(sub.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4">
                      <span className="px-2 py-1 bg-white/5 border border-white/10 rounded text-sm text-gray-600 uppercase tracking-wider">
                        {sub.source || 'Website'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {sub.status === 'active' ? (
                          <div className="flex items-center gap-1.5 text-green-400 text-xs">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Active
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-gray-600 text-xs">
                            <XCircle className="w-3.5 h-3.5" />
                            Unsubscribed
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button className="p-2 hover:bg-red-500/10 hover:text-red-400 text-gray-600 rounded-lg transition-all">
                          <Trash2 className="w-4 h-4" />
                        </button>
                        <button className="p-2 hover:bg-white/10 text-gray-600 rounded-lg transition-all">
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="px-6 py-20 text-center text-gray-600">
                    <Users className="w-12 h-12 mx-auto mb-4 opacity-20" />
                    <p>No subscribers found</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
