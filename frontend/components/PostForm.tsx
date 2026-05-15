'use client';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { SPANISH_CATEGORIES } from '@/types';

interface Props {
  post?: {
    id: string;
    title: string;
    slug: string;
    excerpt: string;
    content: string;
    category: string;
    status: string;
    hero_image: string;
    image_alt?: string;
    meta_title: string;
    meta_description: string;
    difficulty?: string;
    estimated_cost?: string;
    prep_time?: number;
    cook_time?: number;
    chef_tip?: string;
    pinterest_pin_id?: string;
  };
}

export default function PostForm({ post }: Props) {
  const router = useRouter();
  const isEdit = !!post;

  const [categories, setCategories] = useState<string[]>(SPANISH_CATEGORIES);
  const [form, setForm] = useState({
    title: post?.title ?? '',
    slug: post?.slug ?? '',
    excerpt: post?.excerpt ?? '',
    content: post?.content ?? '',
    category: post?.category ?? 'Postres',
    status: post?.status ?? 'draft',
    hero_image: post?.hero_image ?? '',
    image_alt: post?.image_alt ?? '',
    meta_title: post?.meta_title ?? '',
    meta_description: post?.meta_description ?? '',
    difficulty: post?.difficulty ?? 'Media',
    estimated_cost: post?.estimated_cost ?? 'Medio',
    prep_time: post?.prep_time ?? 20,
    cook_time: post?.cook_time ?? 30,
    chef_tip: post?.chef_tip ?? '',
    pinterest_pin_id: post?.pinterest_pin_id ?? '',
  });
  
  const [loadingCats, setLoadingCats] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCategories();
  }, []);

  const fetchCategories = async () => {
    try {
      const res = await fetch('/api/admin/settings');
      if (res.ok) {
        const settings = await res.json();
        if (settings.categories && settings.categories.length > 0) {
          setCategories(settings.categories);
          if (!isEdit && !settings.categories.includes(form.category)) {
             setForm(f => ({ ...f, category: settings.categories[0] }));
          }
        }
      }
    } catch (e) {
      console.error("Error fetching categories", e);
    } finally {
      setLoadingCats(false);
    }
  };

  const handleSmartPopulate = () => {
    if (!form.content) {
      alert("Escribe algo de contenido primero para generar los metadatos.");
      return;
    }
    
    // Simple heuristic-based population for now
    // In a real app, this could call an AI endpoint
    const stripped = form.content.replace(/<[^>]*>?/gm, '').trim();
    const generatedExcerpt = stripped.substring(0, 160) + (stripped.length > 160 ? '...' : '');
    
    setForm(prev => ({
      ...prev,
      excerpt: prev.excerpt || generatedExcerpt,
      meta_title: prev.meta_title || prev.title,
      meta_description: prev.meta_description || generatedExcerpt,
      image_alt: prev.image_alt || prev.title,
    }));
    
    alert("Metadatos generados automáticamente basados en tu contenido.");
  };
  const [error, setError] = useState('');

  const autoSlug = (title: string) =>
    title
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9\s-]/g, '')
      .trim()
      .replace(/\s+/g, '-');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: name === 'prep_time' || name === 'cook_time' ? parseInt(value) || 0 : value,
      ...(name === 'title' && !isEdit ? { slug: autoSlug(value) } : {}),
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError('');

    const url = isEdit ? `/api/admin/posts/${post!.id}` : '/api/admin/posts';
    const method = isEdit ? 'PATCH' : 'POST';

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });

    const json = await res.json();
    if (!res.ok) {
      setError(json.error || 'Error al guardar');
      setSaving(false);
      return;
    }

    router.push('/admin');
    router.refresh();
  };

  const fieldClass = "w-full bg-transparent border border-gray-200 px-4 py-3 text-sm text-gray-800 focus:border-gray-900 outline-none transition-colors rounded";
  const labelClass = "block text-sm font-bold uppercase tracking-[0.3em] text-gray-600 mb-2";

  return (
    <form onSubmit={handleSubmit} className="space-y-8" noValidate>
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 text-sm rounded">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="md:col-span-2">
          <label htmlFor="title" className={labelClass}>Título de la receta *</label>
          <input id="title" name="title" type="text" value={form.title} onChange={handleChange} required placeholder="Ej: Paella Valenciana Tradicional" className={fieldClass} />
        </div>

        <div>
          <label htmlFor="slug" className={labelClass}>Slug (URL) *</label>
          <input id="slug" name="slug" type="text" value={form.slug} onChange={handleChange} required placeholder="paella-valenciana-tradicional" className={fieldClass} />
          <p className="text-sm text-gray-600 mt-1">RecetaDolce.com/<strong>{form.slug || 'tu-receta'}</strong></p>
        </div>

        <div>
          <label htmlFor="category" className={labelClass}>Categoría *</label>
          <select id="category" name="category" value={form.category} onChange={handleChange} className={fieldClass}>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {loadingCats && <p className="text-xs text-gray-600 mt-1 animate-pulse">Cargando categorías...</p>}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="difficulty" className={labelClass}>Dificultad</label>
            <select id="difficulty" name="difficulty" value={form.difficulty} onChange={handleChange} className={fieldClass}>
              <option value="Fácil">Fácil</option>
              <option value="Media">Media</option>
              <option value="Difícil">Difícil</option>
            </select>
          </div>
          <div>
            <label htmlFor="estimated_cost" className={labelClass}>Coste</label>
            <select id="estimated_cost" name="estimated_cost" value={form.estimated_cost} onChange={handleChange} className={fieldClass}>
              <option value="Económico">Económico</option>
              <option value="Medio">Medio</option>
              <option value="Premium">Premium</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="prep_time" className={labelClass}>Prep (min)</label>
            <input id="prep_time" name="prep_time" type="number" value={form.prep_time} onChange={handleChange} className={fieldClass} />
          </div>
          <div>
            <label htmlFor="cook_time" className={labelClass}>Cocción (min)</label>
            <input id="cook_time" name="cook_time" type="number" value={form.cook_time} onChange={handleChange} className={fieldClass} />
          </div>
        </div>

        <div>
          <label htmlFor="status" className={labelClass}>Estado</label>
          <select id="status" name="status" value={form.status} onChange={handleChange} className={fieldClass}>
            <option value="draft">Borrador</option>
            <option value="published">Publicada</option>
          </select>
        </div>

        <div className="md:col-span-2">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label htmlFor="hero_image" className={labelClass}>URL de imagen destacada</label>
              <input id="hero_image" name="hero_image" type="url" value={form.hero_image} onChange={handleChange} placeholder="https://..." className={fieldClass} />
              {form.hero_image && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={form.hero_image} alt="Vista previa" className="mt-3 h-24 w-full object-cover rounded border border-gray-100" />
              )}
            </div>
            <div>
              <label htmlFor="image_alt" className={labelClass}>Alt Text (SEO Imagen)</label>
              <input id="image_alt" name="image_alt" type="text" value={form.image_alt} onChange={handleChange} placeholder="Descripción de la foto para Google" className={fieldClass} />
              <p className="text-sm text-gray-600 mt-1">Ej: Plato de paella valenciana con limones frescos</p>
            </div>
          </div>
        </div>

        <div className="md:col-span-2">
          <label htmlFor="pinterest_pin_id" className={labelClass}>Pinterest Pin ID (Opcional)</label>
          <input id="pinterest_pin_id" name="pinterest_pin_id" type="text" value={form.pinterest_pin_id} onChange={handleChange} placeholder="Ej: 472033604715788003" className={fieldClass} />
          <p className="text-sm text-gray-600 mt-1">Si se proporciona, se mostrará el widget oficial de Pinterest al final de la receta.</p>
        </div>
      </div>

      <div>
        <label htmlFor="excerpt" className={labelClass}>Descripción corta (excerpt) *</label>
        <textarea id="excerpt" name="excerpt" value={form.excerpt} onChange={handleChange} required rows={3} placeholder="Una descripción breve y apetitosa de la receta..." className={fieldClass} />
      </div>

      <div>
        <label htmlFor="content" className={labelClass}>Contenido principal (Markdown) *</label>
        <textarea id="content" name="content" value={form.content} onChange={handleChange} required rows={14} placeholder="# Título&#10;&#10;Escribe aquí el cuerpo del artículo en formato Markdown..." className={`${fieldClass} font-mono text-xs`} />
        <p className="text-sm text-gray-600 mt-1">Soporta Markdown: **negrita**, *cursiva*, ## Subtítulo, - listas</p>
      </div>
      
      <div>
        <label htmlFor="chef_tip" className={labelClass}>El Toque Santangelo (Consejo del Chef)</label>
        <textarea id="chef_tip" name="chef_tip" value={form.chef_tip} onChange={handleChange} rows={3} placeholder="Un consejo profesional para elevar el plato..." className={fieldClass} />
        <p className="text-sm text-gray-600 mt-1">Este bloque aparece con un diseño destacado al final de la receta.</p>
      </div>

      <div className="border-t border-gray-100 pt-8">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-xs font-bold uppercase tracking-[0.3em] text-gray-600">SEO & Metadatos</h3>
          <button 
            type="button" 
            onClick={handleSmartPopulate}
            className="text-sm font-bold text-brand-fresa uppercase tracking-widest hover:text-brand-red flex items-center gap-2"
          >
            <span className="w-2 h-2 bg-brand-fresa rounded-full animate-pulse" />
            Auto-Poblar Campos
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="meta_title" className={labelClass}>Meta título</label>
            <input id="meta_title" name="meta_title" type="text" value={form.meta_title} onChange={handleChange} placeholder={`${form.title} | RecetaDolce`} className={fieldClass} />
            <p className="text-sm text-gray-600 mt-1">{form.meta_title.length}/60 caracteres recomendados</p>
          </div>
          <div>
            <label htmlFor="meta_description" className={labelClass}>Meta descripción</label>
            <textarea id="meta_description" name="meta_description" value={form.meta_description} onChange={handleChange} rows={3} placeholder="Descripción para buscadores (150-160 caracteres)..." className={fieldClass} />
            <p className="text-sm text-gray-600 mt-1">{form.meta_description.length}/160 caracteres recomendados</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between pt-4 border-t border-gray-100">
        <button type="button" onClick={() => router.back()} className="text-gray-600 text-xs hover:text-gray-700 font-bold uppercase tracking-widest transition-colors">
          ← Cancelar
        </button>
        <button type="submit" disabled={saving} className="bg-brand-red text-white px-10 py-4 font-bold uppercase tracking-widest text-sm hover:bg-black transition-all duration-300 disabled:opacity-50 rounded-full shadow-lg shadow-brand-red/20">
          {saving ? 'Guardando...' : isEdit ? 'Guardar Cambios' : 'Publicar Receta'}
        </button>
      </div>
    </form>
  );
}
