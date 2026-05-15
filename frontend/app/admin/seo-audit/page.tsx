'use client';

import { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  AlertTriangle, 
  Info, 
  Search, 
  RefreshCw, 
  ChevronRight,
  ExternalLink,
  FileText,
  BarChart3,
  TrendingUp,
  AlertCircle
} from 'lucide-react';
import Link from 'next/link';

interface AuditIssue {
  type: 'error' | 'warning' | 'info';
  label: string;
  message: string;
}

interface AuditResult {
  id: string;
  title: string;
  slug: string;
  score: number;
  issues: AuditIssue[];
  wordCount: number;
}

export default function SEOAuditPage() {
  const [results, setResults] = useState<AuditResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchAudit = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/admin/seo/audit');
      const data = await res.json();
      setResults(data);
    } catch (error) {
      console.error('Audit failed:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAudit();
  }, []);

  const filteredResults = results.filter(res => {
    const matchesSearch = res.title.toLowerCase().includes(searchTerm.toLowerCase());
    if (filter === 'all') return matchesSearch;
    if (filter === 'critical') return matchesSearch && res.issues.some(i => i.type === 'error');
    if (filter === 'healthy') return matchesSearch && res.score > 80;
    return matchesSearch;
  });

  const stats = {
    total: results.length,
    critical: results.filter(r => r.issues.some(i => i.type === 'error')).length,
    averageScore: Math.round(results.reduce((acc, r) => acc + r.score, 0) / (results.length || 1)),
  };

  return (
    <div className="min-h-screen bg-[#0f1115] text-white p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-end mb-8">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-orange-400 to-amber-200 bg-clip-text text-transparent mb-2">
              SEO Post Audit
            </h1>
            <p className="text-gray-600">Scan your recipes for SEO health and content quality</p>
          </div>
          <button 
            onClick={fetchAudit}
            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh Scan
          </button>
        </div>

        {/* Stats Overview */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 bg-blue-500/10 rounded-xl">
                <FileText className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-gray-600">Total Posts</p>
                <p className="text-2xl font-bold">{stats.total}</p>
              </div>
            </div>
          </div>
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 bg-red-500/10 rounded-xl">
                <AlertCircle className="w-6 h-6 text-red-400" />
              </div>
              <div>
                <p className="text-sm text-gray-600">Critical Issues</p>
                <p className="text-2xl font-bold">{stats.critical}</p>
              </div>
            </div>
          </div>
          <div className="bg-[#1a1d23] p-6 rounded-2xl border border-white/5">
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 bg-green-500/10 rounded-xl">
                <TrendingUp className="w-6 h-6 text-green-400" />
              </div>
              <div>
                <p className="text-sm text-gray-600">Avg SEO Score</p>
                <p className="text-2xl font-bold">{stats.averageScore}%</p>
              </div>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-col md:flex-row gap-4 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input 
              type="text"
              placeholder="Search posts..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-12 pr-4 py-3 bg-[#1a1d23] border border-white/10 rounded-xl focus:border-orange-500/50 outline-none transition-all"
            />
          </div>
          <div className="flex bg-[#1a1d23] p-1 rounded-xl border border-white/10">
            {['all', 'critical', 'healthy'].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-6 py-2 rounded-lg capitalize transition-all ${
                  filter === f ? 'bg-orange-500 text-white shadow-lg' : 'text-gray-600 hover:text-white'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Results List */}
        <div className="space-y-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <RefreshCw className="w-8 h-8 text-orange-500 animate-spin" />
              <p className="text-gray-600">Analyzing your recipe catalog...</p>
            </div>
          ) : filteredResults.length > 0 ? (
            filteredResults.map((item) => (
              <div 
                key={item.id}
                className="bg-[#1a1d23] rounded-2xl border border-white/5 overflow-hidden hover:border-white/20 transition-all group"
              >
                <div className="p-6">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="text-xl font-semibold group-hover:text-orange-400 transition-colors">
                          {item.title}
                        </h3>
                        <span className={`px-2 py-0.5 rounded-md text-sm font-bold uppercase tracking-wider ${
                          item.score >= 80 ? 'bg-green-500/10 text-green-400' :
                          item.score >= 50 ? 'bg-amber-500/10 text-amber-400' :
                          'bg-red-500/10 text-red-400'
                        }`}>
                          Score: {item.score}%
                        </span>
                      </div>
                      <p className="text-sm text-gray-600">/{item.slug}</p>
                    </div>
                    <div className="flex gap-2">
                      <Link 
                        href={`/recetas/${item.slug}`} 
                        target="_blank"
                        className="p-2 bg-white/5 hover:bg-white/10 rounded-lg border border-white/10"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </Link>
                      <Link 
                        href={`/admin/posts/${item.id}`} 
                        className="p-2 bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 rounded-lg border border-orange-500/20"
                      >
                        <ChevronRight className="w-4 h-4" />
                      </Link>
                    </div>
                  </div>

                  {item.issues.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
                      {item.issues.map((issue, idx) => (
                        <div 
                          key={idx}
                          className={`flex items-start gap-3 p-3 rounded-xl border ${
                            issue.type === 'error' ? 'bg-red-500/5 border-red-500/20' :
                            issue.type === 'warning' ? 'bg-amber-500/5 border-amber-500/20' :
                            'bg-blue-500/5 border-blue-500/20'
                          }`}
                        >
                          {issue.type === 'error' ? <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" /> :
                           issue.type === 'warning' ? <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" /> :
                           <Info className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />}
                          <div>
                            <p className="text-xs font-bold uppercase tracking-wide opacity-50">{issue.label}</p>
                            <p className="text-sm text-gray-300">{issue.message}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 p-4 bg-green-500/5 border border-green-500/20 rounded-xl text-green-400">
                      <ShieldCheck className="w-5 h-5" />
                      <p className="text-sm font-medium">Perfect SEO health. No issues found.</p>
                    </div>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-20 bg-[#1a1d23] rounded-2xl border border-dashed border-white/10">
              <Search className="w-12 h-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-600 font-medium">No results found for "{searchTerm}"</p>
              <button onClick={() => setSearchTerm('')} className="text-orange-500 text-sm mt-2 hover:underline">Clear search</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
