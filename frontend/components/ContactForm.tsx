'use client';
import { useState } from 'react';

export default function ContactForm() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', message: '' });
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Local placeholder until the site selects a contact delivery provider.
    await new Promise((r) => setTimeout(r, 800));
    setSent(true);
    setLoading(false);
  };

  if (sent) {
    return (
      <div className="py-16 text-center">
        <p className="text-4xl mb-4">✉️</p>
        <h3 className="font-serif text-2xl text-gray-900 mb-3">¡Mensaje enviado!</h3>
        <p className="text-gray-600 text-sm">Te responderemos en 48–72 horas. ¡Gracias por escribirnos!</p>
      </div>
    );
  }

  const fieldClass = "w-full bg-transparent border-b border-gray-200 py-3 text-gray-800 focus:border-gray-900 outline-none transition-colors text-sm";
  const labelClass = "block text-sm font-bold uppercase tracking-[0.3em] text-gray-600 mb-3";

  return (
    <form onSubmit={handleSubmit} className="space-y-8" aria-label="Formulario de contacto">
      <div>
        <label htmlFor="contact-name" className={labelClass}>Nombre completo</label>
        <input id="contact-name" type="text" name="name" required value={form.name} onChange={handleChange} placeholder="Tu nombre" className={fieldClass} />
      </div>
      <div>
        <label htmlFor="contact-email" className={labelClass}>Correo electrónico</label>
        <input id="contact-email" type="email" name="email" required value={form.email} onChange={handleChange} placeholder="tu@email.com" className={fieldClass} />
      </div>
      <div>
        <label htmlFor="contact-subject" className={labelClass}>Asunto</label>
        <select id="contact-subject" name="subject" value={form.subject} onChange={handleChange} className={fieldClass}>
          <option value="">Selecciona un tema</option>
          <option value="colaboracion">Colaboración editorial</option>
          <option value="receta">Enviar una receta</option>
          <option value="prensa">Prensa y medios</option>
          <option value="otro">Otro</option>
        </select>
      </div>
      <div>
        <label htmlFor="contact-message" className={labelClass}>Mensaje</label>
        <textarea id="contact-message" name="message" required rows={5} value={form.message} onChange={handleChange} placeholder="Cuéntanos..." className={`${fieldClass} resize-none`} />
      </div>
      <button
        type="submit"
        disabled={loading}
        className="w-full bg-brand-red text-white py-4 font-bold uppercase tracking-widest text-xs hover:bg-black transition-all duration-300 disabled:opacity-60"
      >
        {loading ? 'Enviando...' : 'Enviar Mensaje'}
      </button>
    </form>
  );
}
