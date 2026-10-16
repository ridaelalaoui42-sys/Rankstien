'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

interface OperatorStatus {
  alive: boolean;
  supervisor_running: boolean;
  production_running: boolean;
  queue: {
    pending: number;
    processing: number;
    retry: number;
    dlq_size: number;
  };
  domains: Array<{
    handle: string;
    domain: string;
    status: string;
    cred_ready: boolean;
    niche?: string;
  }>;
  actions: Record<string, any>;
  timestamp: string;
}

interface PinStats {
  total_posts: number;
  with_pins: number;
  without_pins: number;
  published: number;
  draft: number;
  by_domain: Record<string, any>;
  timestamp: string;
}

export default function OperatorDashboard() {
  const [operatorStatus, setOperatorStatus] = useState<OperatorStatus | null>(null);
  const [pinStats, setPinStats] = useState<PinStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [campaignConfig, setCampaignConfig] = useState({
    workers: 2,
    keywords_per_cycle: 30,
    domains: ['recetadolce', 'recetagenial'],
    success_target: 5,
  });
  const [launchingMode, setLaunchingMode] = useState<string | null>(null);
  const [stoppingMode, setStoppingMode] = useState<string | null>(null);

  // Fetch operator status
  const fetchOperatorStatus = async () => {
    try {
      const response = await fetch('/api/operator/status', { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to fetch operator status');
      const data = await response.json();
      setOperatorStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // Fetch pin stats
  const fetchPinStats = async () => {
    try {
      const response = await fetch('/api/operator/pins', { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to fetch pin stats');
      const data = await response.json();
      setPinStats(data);
    } catch (err) {
      console.error('Failed to fetch pin stats:', err);
    }
  };

  // Initial fetch and set up polling
  useEffect(() => {
    const init = async () => {
      await fetchOperatorStatus();
      await fetchPinStats();
      setLoading(false);
    };

    init();

    // Poll every 5 seconds
    const statusInterval = setInterval(fetchOperatorStatus, 5000);
    const pinInterval = setInterval(fetchPinStats, 5000);

    return () => {
      clearInterval(statusInterval);
      clearInterval(pinInterval);
    };
  }, []);

  // Start campaign
  const handleStartCampaign = async (mode: string) => {
    setLaunchingMode(mode);
    try {
      const response = await fetch('/api/operator/campaign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'start',
          mode,
          config: campaignConfig,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        setError(error.error || 'Failed to start campaign');
      } else {
        // Refresh status immediately
        await fetchOperatorStatus();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start campaign');
    } finally {
      setLaunchingMode(null);
    }
  };

  // Stop process
  const handleStop = async (mode: string) => {
    setStoppingMode(mode);
    try {
      const response = await fetch('/api/operator/campaign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'stop',
          mode,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        setError(error.error || 'Failed to stop process');
      } else {
        await fetchOperatorStatus();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop process');
    } finally {
      setStoppingMode(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-brand-red mx-auto mb-4" />
          <p className="text-gray-600">Loading operator dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="container mx-auto px-4 sm:px-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl font-serif text-gray-900 mb-2">Operator Dashboard</h1>
            <p className="text-sm text-gray-600">Manage RankStein campaigns and monitor production</p>
          </div>
          <Link href="/admin" className="text-sm text-brand-red hover:underline font-bold">
            ← Back to Admin
          </Link>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            <p className="font-bold text-sm">Error</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Status Grid */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white border border-gray-200 p-6 rounded">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Odysseus</p>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${operatorStatus?.alive ? 'bg-green-500' : 'bg-red-500'}`} />
              <p className="text-lg font-bold text-gray-900">
                {operatorStatus?.alive ? 'Online' : 'Offline'}
              </p>
            </div>
          </div>

          <div className="bg-white border border-gray-200 p-6 rounded">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Supervisor</p>
            <div className="flex items-center gap-2">
              <div
                className={`w-3 h-3 rounded-full ${operatorStatus?.supervisor_running ? 'bg-green-500' : 'bg-gray-300'}`}
              />
              <p className="text-lg font-bold text-gray-900">
                {operatorStatus?.supervisor_running ? 'Running' : 'Idle'}
              </p>
            </div>
          </div>

          <div className="bg-white border border-gray-200 p-6 rounded">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Production</p>
            <div className="flex items-center gap-2">
              <div
                className={`w-3 h-3 rounded-full ${operatorStatus?.production_running ? 'bg-blue-500' : 'bg-gray-300'}`}
              />
              <p className="text-lg font-bold text-gray-900">
                {operatorStatus?.production_running ? 'Active' : 'Idle'}
              </p>
            </div>
          </div>

          <div className="bg-white border border-gray-200 p-6 rounded">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Queue</p>
            <p className="text-lg font-bold text-gray-900">
              {operatorStatus?.queue.pending || 0} pending
            </p>
            <p className="text-xs text-gray-600 mt-1">
              {operatorStatus?.queue.processing || 0} processing · {operatorStatus?.queue.retry || 0} retry
            </p>
          </div>
        </div>

        {/* Pin Statistics */}
        {pinStats && (
          <div className="bg-white border border-gray-200 p-6 rounded mb-8">
            <h2 className="text-lg font-bold text-gray-900 mb-4">📍 Pin Statistics</h2>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <p className="text-xs text-gray-600 font-bold uppercase">Total Posts</p>
                <p className="text-2xl font-bold text-gray-900">{pinStats.total_posts}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600 font-bold uppercase">With Pins</p>
                <p className="text-2xl font-bold text-green-600">{pinStats.with_pins}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600 font-bold uppercase">Without Pins</p>
                <p className="text-2xl font-bold text-orange-600">{pinStats.without_pins}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600 font-bold uppercase">Published</p>
                <p className="text-2xl font-bold text-blue-600">{pinStats.published}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600 font-bold uppercase">Drafts</p>
                <p className="text-2xl font-bold text-gray-600">{pinStats.draft}</p>
              </div>
            </div>

            {/* By Domain */}
            {Object.keys(pinStats.by_domain).length > 0 && (
              <div className="mt-6 pt-6 border-t border-gray-200">
                <p className="text-xs font-bold text-gray-600 uppercase mb-4">By Domain</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {Object.entries(pinStats.by_domain).map(([domain, stats]: [string, any]) => (
                    <div key={domain} className="bg-gray-50 p-4 rounded">
                      <p className="font-bold text-gray-900 text-sm mb-2">{domain}</p>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                          <p className="text-gray-600">Total</p>
                          <p className="font-bold text-gray-900">{stats.total}</p>
                        </div>
                        <div>
                          <p className="text-gray-600">Pinned</p>
                          <p className="font-bold text-green-600">{stats.with_pins}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Campaign Control */}
        <div className="bg-white border border-gray-200 p-6 rounded mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-4">🚀 Campaign Control</h2>

          {/* Campaign Config */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6 pb-6 border-b border-gray-200">
            <div>
              <label className="block text-xs font-bold text-gray-600 uppercase mb-2">Workers</label>
              <input
                type="number"
                min="1"
                max="10"
                value={campaignConfig.workers}
                onChange={(e) => setCampaignConfig({ ...campaignConfig, workers: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded font-mono text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-600 uppercase mb-2">Keywords/Cycle</label>
              <input
                type="number"
                min="1"
                max="100"
                value={campaignConfig.keywords_per_cycle}
                onChange={(e) => setCampaignConfig({ ...campaignConfig, keywords_per_cycle: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded font-mono text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-600 uppercase mb-2">Success Target</label>
              <input
                type="number"
                min="1"
                max="50"
                value={campaignConfig.success_target}
                onChange={(e) => setCampaignConfig({ ...campaignConfig, success_target: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded font-mono text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-600 uppercase mb-2">Domains</label>
              <div className="flex flex-col gap-1">
                {['recetadolce', 'recetagenial'].map((d) => (
                  <label key={d} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={campaignConfig.domains.includes(d)}
                      onChange={(e) => {
                        const domains = e.target.checked
                          ? [...campaignConfig.domains, d]
                          : campaignConfig.domains.filter((x) => x !== d);
                        setCampaignConfig({ ...campaignConfig, domains });
                      }}
                      className="w-4 h-4"
                    />
                    <span className="text-xs text-gray-600">{d}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <button
              onClick={() => handleStartCampaign('production')}
              disabled={launchingMode === 'production' || operatorStatus?.production_running}
              className="bg-green-600 text-white px-6 py-3 rounded font-bold hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {launchingMode === 'production' ? 'Starting...' : 'Start Production Campaign'}
            </button>

            <button
              onClick={() => handleStartCampaign('supervisor')}
              disabled={launchingMode === 'supervisor' || operatorStatus?.supervisor_running}
              className="bg-blue-600 text-white px-6 py-3 rounded font-bold hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {launchingMode === 'supervisor' ? 'Starting...' : 'Start Supervisor'}
            </button>

            <button
              onClick={() => handleStartCampaign('full')}
              disabled={launchingMode === 'full'}
              className="bg-purple-600 text-white px-6 py-3 rounded font-bold hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {launchingMode === 'full' ? 'Starting...' : 'Full Launch'}
            </button>
          </div>

          {/* Stop Buttons */}
          {(operatorStatus?.production_running || operatorStatus?.supervisor_running) && (
            <div className="mt-4 pt-4 border-t border-gray-200">
              <p className="text-xs font-bold text-gray-600 uppercase mb-3">Stop Running Processes</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {operatorStatus?.production_running && (
                  <button
                    onClick={() => handleStop('production')}
                    disabled={stoppingMode === 'production'}
                    className="bg-red-100 text-red-700 px-4 py-2 rounded font-bold hover:bg-red-200 disabled:bg-gray-400 disabled:text-white transition-colors text-sm"
                  >
                    {stoppingMode === 'production' ? 'Stopping...' : '⏹ Stop Production'}
                  </button>
                )}
                {operatorStatus?.supervisor_running && (
                  <button
                    onClick={() => handleStop('supervisor')}
                    disabled={stoppingMode === 'supervisor'}
                    className="bg-red-100 text-red-700 px-4 py-2 rounded font-bold hover:bg-red-200 disabled:bg-gray-400 disabled:text-white transition-colors text-sm"
                  >
                    {stoppingMode === 'supervisor' ? 'Stopping...' : '⏹ Stop Supervisor'}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Domains */}
        {operatorStatus?.domains && (
          <div className="bg-white border border-gray-200 p-6 rounded">
            <h2 className="text-lg font-bold text-gray-900 mb-4">🌐 Domains</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {operatorStatus.domains.map((domain) => (
                <div key={domain.handle} className="border border-gray-200 p-4 rounded">
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      <p className="font-bold text-gray-900">{domain.handle}</p>
                      <p className="text-xs text-gray-600">{domain.domain}</p>
                    </div>
                    <div
                      className={`w-3 h-3 rounded-full ${domain.cred_ready ? 'bg-green-500' : 'bg-red-500'}`}
                    />
                  </div>
                  <p className="text-xs text-gray-600">{domain.niche}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
