'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { 
  FaSave, 
  FaGlobe, 
  FaShareAlt, 
  FaCode, 
  FaChartLine, 
  FaPlus, 
  FaTrash,
  FaChevronRight,
  FaCog
} from 'react-icons/fa';
import { Settings } from '@/types';
import Link from 'next/link';

export default function AdminSettings() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<'general' | 'social' | 'analytics' | 'code' | 'menus' | 'categories' | 'tools' | 'ads'>('general');
  const [settings, setSettings] = useState<Partial<Settings>>({
    site_name: 'RecetaDolce',
    site_description: '',
    contact_email: '',
    navigation_menu: [],
    categories: [],
    ads_enabled: false,
    adsense_client_id: '',
    ads_top_slot: '',
    ads_middle_slot: '',
    ads_bottom_slot: '',
    ads_sidebar_slot: ''
  });

  const [posts, setPosts] = useState<any[]>([]);
  const [auditResults, setAuditResults] = useState<{ id: string, title: string, issues: string[] }[]>([]);
  const [subscribers, setSubscribers] = useState<{ email: string, date: string }[]>([]);
  const [internalLinkSuggestions, setInternalLinkSuggestions] = useState<{ sourcePost: any, targetPost: any, keyword: string }[]>([]);
  const [auditing, setAuditing] = useState(false);
  const [linking, setLinking] = useState(false);

  useEffect(() => {
    fetchSettings();
    fetchPosts();
    // In a real app, you'd fetch subscribers from a table
    setSubscribers([
      { email: 'ejemplo@correo.com', date: '2024-04-20' },
      { email: 'usuario2@gmail.com', date: '2024-04-21' }
    ]);
  }, []);

  const fetchPosts = async () => {
    try {
      const res = await fetch('/api/posts');
      if (res.ok) {
        const data = await res.json();
        setPosts(data);
      }
    } catch (error) {
      console.error('Error fetching posts:', error);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await fetch('/api/admin/settings');
      if (res.ok) {
        const data = await res.json();
        setSettings({
          ...data,
          navigation_menu: data.navigation_menu || [],
          categories: data.categories || []
        });
      }
    } catch (error) {
      console.error('Error fetching settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      if (res.ok) {
        alert('Configuración guardada correctamente');
      } else {
        const err = await res.json();
        alert('Error: ' + err.error);
      }
    } catch (error) {
      alert('Error al guardar');
    } finally {
      setSaving(false);
    }
  };

  const addMenuItem = () => {
    const newMenu = [...(settings.navigation_menu || []), { label: 'Nuevo Enlace', href: '/' }];
    setSettings({ ...settings, navigation_menu: newMenu });
  };

  const removeMenuItem = (index: number) => {
    const newMenu = (settings.navigation_menu || []).filter((_, i) => i !== index);
    setSettings({ ...settings, navigation_menu: newMenu });
  };

  const updateMenuItem = (index: number, field: 'label' | 'href', value: string) => {
    const newMenu = [...(settings.navigation_menu || [])];
    newMenu[index] = { ...newMenu[index], [field]: value };
    setSettings({ ...settings, navigation_menu: newMenu });
  };

  const updateCategory = (index: number, value: string) => {
    const newCats = [...(settings.categories || [])];
    newCats[index] = value;
    setSettings({ ...settings, categories: newCats });
  };

  const [newCatName, setNewCatName] = useState('');

  const addCategory = () => {
    if (newCatName) {
      const newCats = [...(settings.categories || []), newCatName];
      setSettings({ ...settings, categories: newCats });
      setNewCatName('');
    }
  };

  const addCategoryToMenu = (cat: string) => {
    const slug = cat.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, '-');
    const newMenu = [...(settings.navigation_menu || []), { label: cat, href: `/categoria/${slug}` }];
    setSettings({ ...settings, navigation_menu: newMenu });
    alert(`Categoría "${cat}" añadida al menú de navegación.`);
  };

  const removeCategory = (index: number) => {
    const newCats = (settings.categories || []).filter((_, i) => i !== index);
    setSettings({ ...settings, categories: newCats });
  };

  const runSEOAudit = () => {
    setAuditing(true);
    const results: any[] = [];
    
    posts.forEach(post => {
      const issues = [];
      if (!post.hero_image) issues.push('Falta imagen destacada');
      if (!post.meta_description) issues.push('Falta meta descripción');
      if (post.content && post.content.length < 500) issues.push('Contenido muy corto (SEO pobre)');
      if (!post.image_alt) issues.push('Falta texto ALT en imagen');
      
      if (issues.length > 0) {
        results.push({ id: post.id, title: post.title, issues });
      }
    });

    setTimeout(() => {
      setAuditResults(results);
      setAuditing(false);
    }, 1500);
  };

  const runInternalLinker = () => {
    setLinking(true);
    const suggestions: any[] = [];
    
    // Simple algorithm: look for post titles inside other post's content
    posts.forEach(sourcePost => {
      posts.forEach(targetPost => {
        if (sourcePost.id === targetPost.id) return;
        
        // Use a simple keyword from the title
        const keyword = targetPost.title.split(' ').filter((w: string) => w.length > 5)[0];
        if (keyword && sourcePost.content?.toLowerCase().includes(keyword.toLowerCase())) {
          // Check if it already has a link to this slug
          if (!sourcePost.content.includes(targetPost.slug)) {
            suggestions.push({
              sourcePost,
              targetPost,
              keyword
            });
          }
        }
      });
    });

    setTimeout(() => {
      setInternalLinkSuggestions(suggestions.slice(0, 10)); // Limit to top 10
      setLinking(false);
    }, 1500);
  };

  if (loading) return <div className="flex justify-center items-center h-screen bg-white text-brand-fresa font-serif italic text-xl">Cargando RecetaDolce...</div>;

  return (
    <div className="min-h-screen bg-[#fafafa] pb-20">
      {/* Header */}
      <div className="bg-white border-b border-gray-100 py-6 mb-8 sticky top-0 z-30 shadow-sm">
        <div className="container mx-auto px-6 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <Link href="/admin" className="text-gray-600 hover:text-brand-fresa transition-colors flex items-center gap-2">
              <FaCog size={14} />
              Panel
            </Link>
            <FaChevronRight size={10} className="text-gray-300" />
            <h1 className="text-2xl font-serif text-ink font-bold">Ajustes del Sistema</h1>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-8 py-3 bg-brand-fresa text-white rounded-full text-sm font-bold uppercase tracking-widest hover:bg-brand-red transition-all shadow-xl shadow-brand-fresa/20 disabled:opacity-50"
          >
            {saving ? 'Guardando...' : (
              <>
                <FaSave />
                Guardar Configuración
              </>
            )}
          </button>
        </div>
      </div>

      <div className="container mx-auto px-6">
        <div className="flex flex-col lg:flex-row gap-12">
          {/* Sidebar Tabs */}
          <div className="w-full lg:w-72 flex flex-row lg:flex-col gap-2 overflow-x-auto pb-4 lg:pb-0 scrollbar-hide">
            {[
              { id: 'general', label: 'General', icon: FaGlobe },
              { id: 'categories', label: 'Categorías', icon: FaPlus },
              { id: 'social', label: 'Social', icon: FaShareAlt },
              { id: 'analytics', label: 'Analíticas', icon: FaChartLine },
              { id: 'code', label: 'Código', icon: FaCode },
              { id: 'menus', label: 'Navegación', icon: FaCog },
              { id: 'ads', label: 'Anuncios', icon: FaChartLine },
              { id: 'tools', label: 'Herramientas SEO', icon: FaChartLine }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-3 px-6 py-4 rounded-xl text-sm font-bold uppercase tracking-widest transition-all whitespace-nowrap border ${
                  activeTab === tab.id 
                  ? 'bg-brand-fresa text-white shadow-lg shadow-brand-fresa/20 border-brand-fresa' 
                  : 'bg-white text-gray-600 hover:bg-gray-50 border-gray-100'
                }`}
              >
                <tab.icon size={14} />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Main Form */}
          <div className="flex-grow">
            <div className="bg-white rounded-[2rem] border border-gray-100 shadow-sm p-8 md:p-12 animate-fade-up">
              
              {/* General Settings */}
              {activeTab === 'general' && (
                <div className="space-y-8">
                  <h2 className="text-xl font-serif font-bold text-ink mb-8 pb-4 border-b border-gray-50">Configuración General</h2>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Nombre del Sitio</label>
                      <input
                        type="text"
                        value={settings.site_name}
                        onChange={(e) => setSettings({...settings, site_name: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Email de Contacto</label>
                      <input
                        type="email"
                        value={settings.contact_email}
                        onChange={(e) => setSettings({...settings, contact_email: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Descripción del Sitio (SEO)</label>
                    <textarea
                      value={settings.site_description}
                      onChange={(e) => setSettings({...settings, site_description: e.target.value})}
                      rows={4}
                      className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all resize-none"
                    />
                  </div>
                </div>
              )}

              {/* Social Media */}
              {activeTab === 'social' && (
                <div className="space-y-8">
                  <h2 className="text-xl font-serif font-bold text-ink mb-8 pb-4 border-b border-gray-50">Redes Sociales</h2>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    {[
                      { key: 'facebook_url', label: 'Facebook', color: 'blue' },
                      { key: 'instagram_url', label: 'Instagram', color: 'pink' },
                      { key: 'pinterest_url', label: 'Pinterest', color: 'red' },
                      { key: 'twitter_url', label: 'Twitter (X)', color: 'black' },
                      { key: 'youtube_url', label: 'YouTube', color: 'red' },
                      { key: 'tiktok_url', label: 'TikTok', color: 'black' }
                    ].map((social) => (
                      <div key={social.key} className="space-y-2">
                        <label className="text-sm font-bold uppercase tracking-widest text-gray-600">{social.label}</label>
                        <input
                          type="url"
                          value={(settings as any)[social.key] || ''}
                          onChange={(e) => setSettings({...settings, [social.key]: e.target.value})}
                          placeholder="https://..."
                          className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Analytics */}
              {activeTab === 'analytics' && (
                <div className="space-y-8">
                  <h2 className="text-xl font-serif font-bold text-ink mb-8 pb-4 border-b border-gray-50">Google Analytics & Tags</h2>
                  <div className="bg-blue-50 p-6 rounded-2xl border border-blue-100 mb-8">
                    <p className="text-blue-800 text-sm leading-relaxed">
                      Inserta tu <strong>Measurement ID (G-XXXXXXXXXX)</strong> para habilitar Google Analytics de forma automática. 
                      Para otros tags (Facebook Pixel, etc.), usa la pestaña de Código Custom.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Google Analytics ID</label>
                    <input
                      type="text"
                      value={settings.google_analytics_id || ''}
                      onChange={(e) => setSettings({...settings, google_analytics_id: e.target.value})}
                      placeholder="G-..."
                      className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                    />
                  </div>
                </div>
              )}

              {/* Custom Code */}
              {activeTab === 'code' && (
                <div className="space-y-8">
                  <h2 className="text-xl font-serif font-bold text-ink mb-8 pb-4 border-b border-gray-50">Inyección de Código</h2>
                  <div className="space-y-6">
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Header Code (Scripts en &lt;head&gt;)</label>
                      <textarea
                        value={settings.custom_head_code || ''}
                        onChange={(e) => setSettings({...settings, custom_head_code: e.target.value})}
                        rows={8}
                        className="w-full px-6 py-4 bg-gray-900 text-green-400 font-mono text-xs rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all resize-none"
                        placeholder="<!-- Scripts de tracking, CSS custom, etc. -->"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Footer Code (Scripts antes de &lt;/body&gt;)</label>
                      <textarea
                        value={settings.custom_footer_code || ''}
                        onChange={(e) => setSettings({...settings, custom_footer_code: e.target.value})}
                        rows={8}
                        className="w-full px-6 py-4 bg-gray-900 text-green-400 font-mono text-xs rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all resize-none"
                        placeholder="<!-- Scripts de chat, widgets, etc. -->"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Navigation Menus */}
              {activeTab === 'menus' && (
                <div className="space-y-8">
                  <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                    <h2 className="text-xl font-serif font-bold text-ink">Menú Principal</h2>
                    <button
                      onClick={addMenuItem}
                      className="flex items-center gap-2 text-brand-fresa text-sm font-bold uppercase tracking-widest hover:text-brand-red"
                    >
                      <FaPlus size={10} />
                      Añadir Link
                    </button>
                  </div>
                  <div className="space-y-4">
                    {(settings.navigation_menu || []).map((item, i) => (
                      <div key={i} className="flex gap-4 items-end bg-gray-50 p-4 rounded-xl border border-gray-100">
                        <div className="flex-grow space-y-2">
                          <label className="text-xs font-bold uppercase tracking-widest text-gray-600">Etiqueta</label>
                          <input
                            type="text"
                            value={item.label}
                            onChange={(e) => updateMenuItem(i, 'label', e.target.value)}
                            className="w-full px-4 py-2 bg-white border border-gray-200 rounded-lg outline-none focus:border-brand-fresa text-sm"
                          />
                        </div>
                        <div className="flex-[2] space-y-2">
                          <label className="text-xs font-bold uppercase tracking-widest text-gray-600">URL / Ruta</label>
                          <input
                            type="text"
                            value={item.href}
                            onChange={(e) => updateMenuItem(i, 'href', e.target.value)}
                            className="w-full px-4 py-2 bg-white border border-gray-200 rounded-lg outline-none focus:border-brand-fresa text-sm"
                          />
                        </div>
                        <button
                          onClick={() => removeMenuItem(i)}
                          className="p-3 text-gray-300 hover:text-brand-red transition-colors mb-0.5"
                        >
                          <FaTrash size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Categories */}
              {activeTab === 'categories' && (
                <div className="space-y-8">
                  <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                    <h2 className="text-xl font-serif font-bold text-ink">Gestión de Categorías</h2>
                    <button
                      onClick={addCategory}
                      className="flex items-center gap-2 text-brand-fresa text-sm font-bold uppercase tracking-widest hover:text-brand-red"
                    >
                      <FaPlus size={10} />
                      Nueva Categoría
                    </button>
                  </div>
                  <div className="bg-gray-50 p-6 rounded-2xl border border-gray-100 mb-8">
                    <div className="flex gap-4">
                      <input
                        type="text"
                        placeholder="Nombre de la nueva categoría (ej: Vegano, Postres Rápidos)"
                        value={newCatName}
                        onChange={(e) => setNewCatName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && addCategory()}
                        className="flex-grow px-6 py-3 bg-white border border-gray-200 rounded-xl outline-none focus:border-brand-fresa shadow-sm"
                      />
                      <button
                        onClick={addCategory}
                        className="px-8 py-3 bg-brand-fresa text-white rounded-xl font-bold uppercase tracking-widest text-xs hover:bg-brand-red transition-all shadow-lg shadow-brand-fresa/10"
                      >
                        Añadir
                      </button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {(settings.categories || []).map((cat, i) => (
                      <div key={i} className="flex flex-col bg-white p-5 rounded-2xl border border-gray-100 group hover:border-brand-fresa transition-all shadow-sm hover:shadow-md">
                        <div className="flex justify-between items-center mb-4">
                          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Categoría #{i+1}</span>
                          <button
                            onClick={() => removeCategory(i)}
                            className="text-gray-300 hover:text-brand-red transition-all"
                            title="Eliminar categoría"
                          >
                            <FaTrash size={12} />
                          </button>
                        </div>
                        <input
                          type="text"
                          value={cat}
                          onChange={(e) => updateCategory(i, e.target.value)}
                          className="w-full px-4 py-2 bg-gray-50 border border-transparent rounded-lg outline-none focus:bg-white focus:border-brand-fresa transition-all text-sm font-bold text-ink"
                        />
                        <button
                          onClick={() => addCategoryToMenu(cat)}
                          className="mt-4 text-[10px] font-bold text-brand-fresa uppercase tracking-widest hover:text-brand-red flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all"
                        >
                          <FaPlus size={8} /> Añadir al Menú
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* SEO Tools */}
              {activeTab === 'tools' && (
                <div className="space-y-12">
                  <section>
                    <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                      <h2 className="text-xl font-serif font-bold text-ink">Auditoría SEO de Posts</h2>
                      <button
                        onClick={runSEOAudit}
                        disabled={auditing}
                        className="px-6 py-2 bg-ink text-white text-sm font-bold uppercase tracking-widest rounded-full hover:bg-black transition-all disabled:opacity-50"
                      >
                        {auditing ? 'Escaneando...' : 'Iniciar Escaneo'}
                      </button>
                    </div>

                    {auditResults.length > 0 ? (
                      <div className="space-y-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                        {auditResults.map((res, i) => (
                          <div key={i} className="p-6 bg-red-50 rounded-2xl border border-red-100">
                            <h3 className="font-bold text-red-900 text-sm mb-2">{res.title}</h3>
                            <ul className="space-y-1">
                              {res.issues.map((issue, j) => (
                                <li key={j} className="text-xs text-red-700 flex items-center gap-2">
                                  <span className="w-1 h-1 bg-red-400 rounded-full" />
                                  {issue}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-12 bg-gray-50 rounded-3xl border border-dashed border-gray-200">
                        <p className="text-gray-600 font-serif italic text-sm">Inicia el escaneo para encontrar problemas de SEO.</p>
                      </div>
                    )}
                  </section>

                  <section>
                    <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                      <h2 className="text-xl font-serif font-bold text-ink">Sugerencias de Enlaces Internos</h2>
                      <button
                        onClick={runInternalLinker}
                        disabled={linking}
                        className="px-6 py-2 bg-ink text-white text-sm font-bold uppercase tracking-widest rounded-full hover:bg-black transition-all disabled:opacity-50"
                      >
                        {linking ? 'Analizando...' : 'Analizar Enlaces'}
                      </button>
                    </div>

                    {internalLinkSuggestions.length > 0 ? (
                      <div className="space-y-4">
                        {internalLinkSuggestions.map((sug, i) => (
                          <div key={i} className="p-6 bg-blue-50 rounded-2xl border border-blue-100 flex justify-between items-center">
                            <div>
                              <p className="text-xs text-blue-800 font-medium">Sugerencia de Link:</p>
                              <h4 className="text-sm font-bold text-ink">
                                Vincular "{sug.sourcePost.title}" con "{sug.targetPost.title}"
                              </h4>
                              <p className="text-xs text-blue-600 mt-1 italic">Vía palabra clave: "{sug.keyword}"</p>
                            </div>
                            <Link 
                              href={`/admin/edit/${sug.sourcePost.id}`}
                              className="px-4 py-2 bg-white text-brand-fresa border border-brand-fresa rounded-full text-sm font-bold hover:bg-brand-fresa hover:text-white transition-all"
                            >
                              Editar Post
                            </Link>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-12 bg-gray-50 rounded-3xl border border-dashed border-gray-200">
                        <p className="text-gray-600 font-serif italic text-sm">Analiza tus posts para encontrar oportunidades de enlaces internos.</p>
                      </div>
                    )}
                  </section>

                  <section>
                    <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                      <h2 className="text-xl font-serif font-bold text-ink">Newsletter & Suscriptores</h2>
                      <span className="px-3 py-1 bg-green-100 text-green-700 text-sm font-bold rounded-full">
                        {subscribers.length} SUSCRIPTORES
                      </span>
                      <button 
                        onClick={async () => {
                          const subject = prompt('Asunto de la newsletter:', 'Novedades en RecetaDolce');
                          const msg = prompt('Escribe el mensaje de la newsletter:');
                          if (msg) {
                            try {
                              const res = await fetch('/api/admin/newsletter/send', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ subject, message: msg })
                              });
                              const data = await res.json();
                              if (res.ok) alert(data.message);
                              else alert('Error: ' + data.error);
                            } catch (e) {
                              alert('Error de conexión');
                            }
                          }
                        }}
                        className="px-6 py-2 bg-brand-fresa text-white text-sm font-bold uppercase tracking-widest rounded-full hover:bg-brand-red transition-all"
                      >
                        Enviar Newsletter
                      </button>
                    </div>
                    <div className="bg-white border border-gray-100 rounded-2xl overflow-hidden">
                      <table className="w-full text-left text-sm">
                        <thead className="bg-gray-50 border-b border-gray-100">
                          <tr>
                            <th className="px-6 py-4 font-bold text-sm uppercase tracking-widest text-gray-600">Email</th>
                            <th className="px-6 py-4 font-bold text-sm uppercase tracking-widest text-gray-600">Fecha</th>
                            <th className="px-6 py-4 font-bold text-sm uppercase tracking-widest text-gray-600 text-right">Acciones</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                          {subscribers.map((sub, i) => (
                            <tr key={i} className="hover:bg-gray-50/50 transition-colors">
                              <td className="px-6 py-4 font-medium text-ink">{sub.email}</td>
                              <td className="px-6 py-4 text-gray-600">{sub.date}</td>
                              <td className="px-6 py-4 text-right">
                                <button className="text-gray-300 hover:text-brand-fresa transition-colors">
                                  <FaShareAlt size={12} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </div>
              )}

              {/* Ads Settings */}
              {activeTab === 'ads' && (
                <div className="space-y-8">
                  <div className="flex justify-between items-center mb-8 pb-4 border-b border-gray-50">
                    <h2 className="text-xl font-serif font-bold text-ink">Configuración de Publicidad</h2>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold uppercase tracking-widest text-gray-600">Habilitar Anuncios</span>
                      <button
                        onClick={() => setSettings({...settings, ads_enabled: !settings.ads_enabled})}
                        className={`w-12 h-6 rounded-full transition-all relative ${settings.ads_enabled ? 'bg-brand-fresa' : 'bg-gray-200'}`}
                      >
                        <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${settings.ads_enabled ? 'left-7' : 'left-1'}`} />
                      </button>
                    </div>
                  </div>

                  <div className="bg-amber-50 p-6 rounded-2xl border border-amber-100 mb-8">
                    <p className="text-amber-800 text-sm leading-relaxed">
                      <strong>Importante:</strong> Para que los anuncios funcionen, debes tener una cuenta de Google AdSense aprobada. 
                      Ingresa tu <strong>Client ID</strong> (ca-pub-...) y los <strong>Slot IDs</strong> de tus unidades de anuncios.
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">AdSense Client ID</label>
                      <input
                        type="text"
                        value={settings.adsense_client_id || ''}
                        onChange={(e) => setSettings({...settings, adsense_client_id: e.target.value})}
                        placeholder="ca-pub-xxxxxxxxxxxxxxxx"
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-4">
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Slot ID: Top (Cabecera)</label>
                      <input
                        type="text"
                        value={settings.ads_top_slot || ''}
                        onChange={(e) => setSettings({...settings, ads_top_slot: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Slot ID: Middle (Contenido)</label>
                      <input
                        type="text"
                        value={settings.ads_middle_slot || ''}
                        onChange={(e) => setSettings({...settings, ads_middle_slot: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Slot ID: Bottom (Final)</label>
                      <input
                        type="text"
                        value={settings.ads_bottom_slot || ''}
                        onChange={(e) => setSettings({...settings, ads_bottom_slot: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-bold uppercase tracking-widest text-gray-600">Slot ID: Sidebar (Lateral)</label>
                      <input
                        type="text"
                        value={settings.ads_sidebar_slot || ''}
                        onChange={(e) => setSettings({...settings, ads_sidebar_slot: e.target.value})}
                        className="w-full px-6 py-4 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-brand-fresa/20 focus:border-brand-fresa outline-none transition-all"
                      />
                    </div>
                  </div>
                </div>
              )}

            </div>
            
            {/* Bottom Save Bar for Mobile/UX */}
            <div className="mt-12 pt-8 border-t border-gray-100 flex justify-end">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-3 px-10 py-4 bg-brand-fresa text-white rounded-full text-sm font-bold uppercase tracking-widest hover:bg-brand-red transition-all shadow-xl shadow-brand-fresa/20 disabled:opacity-50"
              >
                {saving ? 'Guardando...' : (
                  <>
                    <FaSave />
                    Guardar Cambios
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
