"use client";

import React from 'react';

interface RecipeDetailsProps {
  ingredients: string[];
  instructions?: any[];
  nutrition?: {
    calories?: string;
    proteinContent?: string;
    protein?: string;
    fatContent?: string;
    fat?: string;
    carbohydrateContent?: string;
    carbs?: string;
    servingSize?: string;
  };
  prepTime?: string;
  cookTime?: string;
  yields?: string | number;
  title?: string;
}

// Helper to format ISO 8601 durations (e.g., PT20M -> 20 min)
const formatDuration = (duration?: string) => {
  if (!duration) return '--';
  if (!duration.startsWith('PT')) return duration;
  
  const match = duration.match(/PT(?:(\d+)H)?(?:(\d+)M)?/);
  if (!match) return duration;
  
  const hours = match[1] ? `${match[1]}h ` : '';
  const minutes = match[2] ? `${match[2]} min` : '';
  return `${hours}${minutes}`.trim() || '0 min';
};

// Helper to normalize instructions (handle string[] or HowToStep[])
const normalizeInstructions = (steps: any[]): string[] => {
  if (!Array.isArray(steps)) return [];
  return steps.map(step => {
    if (typeof step === 'string') return step;
    if (step && typeof step === 'object' && step.text) return step.text;
    return '';
  }).filter(Boolean);
};

export default function RecipeDetails({ 
  ingredients = [], 
  instructions = [], 
  nutrition, 
  prepTime, 
  cookTime, 
  yields,
  title
}: RecipeDetailsProps) {
  const [servings, setServings] = React.useState(Number(yields) || 4);
  const [isCookMode, setIsCookMode] = React.useState(false);
  const [checkedIngredients, setCheckedIngredients] = React.useState<number[]>([]);
  const [checkedSteps, setCheckedSteps] = React.useState<number[]>([]);
  
  const handlePrint = () => {
    window.print();
  };

  const toggleIngredient = (idx: number) => {
    if (!isCookMode) return;
    setCheckedIngredients(prev => 
      prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]
    );
  };

  const toggleStep = (idx: number) => {
    if (!isCookMode) return;
    setCheckedSteps(prev => 
      prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]
    );
  };

  const normalizedSteps = normalizeInstructions(instructions);

  // Simple ingredient scaling logic
  const scaleIngredient = (ingredient: any) => {
    if (typeof ingredient !== 'string') return String(ingredient || '');
    
    const baseServings = Number(yields) || 4;
    const ratio = servings / baseServings;
    
    // Attempt to find and scale numbers in the string
    return ingredient.replace(/(\d+(?:\.\d+)?)/g, (match) => {
      const num = parseFloat(match);
      if (isNaN(num)) return match;
      const scaled = num * ratio;
      return scaled % 1 === 0 ? scaled.toString() : scaled.toFixed(1);
    });
  };

  return (
    <div id="recipe-box" className="group relative my-16 scroll-mt-24">
      {/* Subtle brand glow behind the card */}
      <div className="absolute -inset-2 bg-brand-fresa/10 rounded-[3rem] blur-3xl opacity-10 group-hover:opacity-30 transition duration-1000"></div>
      
      <div className="relative recipe-card border border-brand-fresa/10 bg-white shadow-xl rounded-[1rem] md:rounded-[2rem] overflow-hidden print:border-none print:shadow-none print:bg-white print:rounded-none transition-all duration-700">
        
        {/* Compact Header */}
        <div className="bg-[#5D0000] px-6 py-6 md:px-10 md:py-8 flex flex-col md:flex-row justify-between items-center text-center md:text-left space-y-4 md:space-y-0 print:bg-none print:bg-white print:px-0 print:py-6 print:border-b-2 print:border-brand-fresa">
          <div className="space-y-2 max-w-2xl">
            <div className="flex items-center justify-center md:justify-start space-x-4 mb-1">
              <span className="w-8 h-px bg-white/20"></span>
              <h2 className="text-xs font-bold uppercase tracking-[0.5em] text-white/50">
                RECETA PASO A PASO
              </h2>
            </div>
            <div className="text-3xl md:text-4xl lg:text-5xl font-serif text-white leading-tight print:text-ink">{title}</div>
          </div>

          <div className="flex flex-col sm:flex-row items-center space-y-3 sm:space-y-0 sm:space-x-4 print:hidden">
            <button 
              onClick={() => setIsCookMode(!isCookMode)}
              className={`flex items-center space-x-3 px-6 py-3 rounded-full transition-all duration-700 border-2 ${
                isCookMode 
                ? 'bg-brand-fresa border-brand-fresa text-white shadow-lg' 
                : 'bg-white/5 border-white/10 text-white hover:bg-white/10 hover:border-white/20'
              }`}
            >
              <div className={`w-2 h-2 rounded-full ${isCookMode ? 'bg-white animate-pulse' : 'bg-white/30'}`} />
              <span className="text-xs font-bold uppercase tracking-[0.2em]">
                {isCookMode ? 'MODO COCINA' : 'COCINAR'}
              </span>
            </button>
            <button 
              onClick={handlePrint}
              className="group/btn flex items-center space-x-3 px-6 py-3 bg-white text-ink rounded-full transition-all duration-700 hover:bg-brand-fresa hover:text-white shadow-lg"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
              </svg>
              <span className="text-xs font-bold uppercase tracking-[0.2em]">Imprimir</span>
            </button>
          </div>
        </div>

        <div className="p-6 md:p-10 lg:p-12">
          {/* Editorial Stats Grid - Architectural Excellence */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-12 print:mb-8 mx-auto">
            {[
              { label: 'Preparación', value: formatDuration(prepTime || "PT15M"), icon: '⏱️' },
              { label: 'Cocción', value: formatDuration(cookTime || "PT20M"), icon: '🔥' },
              { label: 'Dificultad', value: 'Media', icon: '✨' },
              { label: 'Calorías', value: `${(nutrition?.calories?.toString() || '450').split(' ')[0]} kcal`, icon: '🥗' }
            ].map((stat, i) => (
              <div key={i} className="group/stat relative rounded-[1.5rem] p-4 md:p-6 border bg-white border-gray-100 flex flex-col items-center justify-center text-center transition-all duration-700 shadow-sm print:p-2">
                <span className="text-xl mb-2 print:hidden">{stat.icon}</span>
                <span className="text-sm font-bold uppercase tracking-[0.3em] text-gray-600 mb-1">{stat.label}</span>
                <span className="text-lg font-serif text-ink">{stat.value}</span>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-8 md:gap-12">
            {/* Ingredients Area */}
            <div className="md:col-span-5 space-y-8">
              <section className="bg-cream-base/50 p-4 md:p-6 rounded-[1.2rem] border border-brand-fresa/10 relative overflow-hidden">
                <div className="flex flex-col mb-6">
                  <span className="text-editorial text-brand-fresa mb-2 text-sm">Mise en place</span>
                  <h3 className="text-2xl font-serif text-ink italic">Ingredientes</h3>
                  
                  {/* Dynamic Servings Dial */}
                  <div className="mt-6 p-3 bg-white rounded-xl border border-brand-fresa/10 flex items-center justify-between print:hidden">
                    <span className="text-xs font-bold uppercase tracking-widest text-gray-600">Porciones</span>
                    <div className="flex items-center space-x-4">
                      <button 
                        onClick={() => setServings(Math.max(1, servings - 1))}
                        className="w-8 h-8 rounded-full border border-brand-fresa/20 flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all shadow-sm"
                      >
                        -
                      </button>
                      <span className="text-xl font-serif text-ink w-6 text-center">{servings}</span>
                      <button 
                        onClick={() => setServings(servings + 1)}
                        className="w-8 h-8 rounded-full border border-brand-fresa/20 flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all shadow-sm"
                      >
                        +
                      </button>
                    </div>
                  </div>
                </div>

                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                  {Array.isArray(ingredients) && ingredients.map((ingredient, idx) => (
                    <li 
                      key={idx} 
                      onClick={() => toggleIngredient(idx)}
                      className={`flex items-start group/item transition-all duration-500 ${isCookMode ? 'cursor-pointer' : ''} ${
                        isCookMode && checkedIngredients.includes(idx) ? 'opacity-40 scale-[0.98]' : ''
                      }`}
                    >
                      <div className="mt-1.5 mr-4 flex-shrink-0 relative">
                        <div className={`w-3.5 h-3.5 rounded-full border-2 transition-all duration-500 ${
                          isCookMode && checkedIngredients.includes(idx) 
                          ? 'bg-brand-fresa border-brand-fresa scale-110' 
                          : 'border-brand-fresa/20 group-hover/item:border-brand-fresa'
                        }`} />
                        {isCookMode && checkedIngredients.includes(idx) && (
                          <div className="absolute inset-0 flex items-center justify-center text-white text-[7px]">
                            ✓
                          </div>
                        )}
                      </div>
                      <span className={`text-gray-600 leading-relaxed font-serif text-sm md:text-base transition-all duration-500 ${
                        isCookMode && checkedIngredients.includes(idx) ? 'line-through decoration-brand-fresa/30' : 'group-hover/item:text-ink'
                      }`}>
                        {scaleIngredient(ingredient)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>

              {nutrition && (
                <section className="bg-cream-dark/30 rounded-[2rem] p-6 relative overflow-hidden group/nutri print:bg-white print:text-ink print:p-0 print:border-none">
                  <h4 className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa mb-6 pb-2 border-b border-brand-fresa/10 print:border-ink">
                    Balance Nutricional
                  </h4>
                  
                  <div className="space-y-6">
                    {[
                      { label: 'Proteínas', value: nutrition.proteinContent || nutrition.protein || '--' },
                      { label: 'Grasas', value: nutrition.fatContent || nutrition.fat || '--' },
                      { label: 'Carbohidratos', value: nutrition.carbohydrateContent || nutrition.carbs || '--' },
                    ].map((n, i) => (
                      <div key={i} className="flex justify-between items-baseline group/val">
                        <span className="text-xs text-gray-600 uppercase tracking-widest font-bold group-hover/val:text-brand-fresa transition-colors">{n.label}</span>
                        <div className="h-px flex-grow mx-4 bg-brand-fresa/5"></div>
                        <span className="text-xl font-serif text-ink">{n.value}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>

            {/* Instructions Area */}
            <div className="md:col-span-7">
              {normalizedSteps.length > 0 && (
                <section>
                  <div className="flex items-center space-x-4 mb-8">
                    <span className="text-editorial text-brand-fresa text-sm">Step by step</span>
                    <h3 className="text-3xl md:text-4xl font-serif text-ink italic">Preparación</h3>
                    <div className="h-px flex-grow bg-brand-fresa/10"></div>
                  </div>
                  
                  <div className="space-y-6 md:space-y-8">
                    {normalizedSteps.map((step, idx) => (
                      <div 
                        key={idx} 
                        onClick={() => toggleStep(idx)}
                        className={`relative flex space-x-6 md:space-x-8 transition-all duration-700 print:block print:space-x-0 print:mb-8 ${
                          isCookMode ? 'cursor-pointer' : ''
                        } ${
                          isCookMode && checkedSteps.includes(idx) ? 'opacity-30' : ''
                        } ${
                          isCookMode && !checkedSteps.includes(idx) && (checkedSteps.length === idx) ? 'scale-105' : ''
                        }`}
                      >
                        <div className="flex-shrink-0 print:hidden relative z-10">
                          <div className={`w-10 h-10 md:w-12 md:h-12 rounded-full border transition-all duration-700 flex items-center justify-center font-serif text-lg italic shadow-sm ${
                            checkedSteps.includes(idx)
                            ? 'bg-brand-fresa border-brand-fresa text-white'
                            : 'bg-white border-brand-fresa/20 text-brand-fresa'
                          }`}>
                            {checkedSteps.includes(idx) ? '✓' : idx + 1}
                          </div>
                        </div>
                        <div className="pt-0.5 md:pt-1">
                          <span className="hidden print:inline font-serif font-bold text-base mr-3">{idx + 1}.</span>
                          <p className={`text-ink text-sm md:text-base leading-relaxed font-serif transition-all duration-500 ${
                            checkedSteps.includes(idx) ? 'line-through opacity-50' : ''
                          }`}>
                            {step}
                          </p>
                        </div>
                        {idx !== normalizedSteps.length - 1 && (
                          <div className={`absolute left-7 md:left-8 top-14 md:top-16 w-px h-[calc(100%+3rem)] transition-all duration-700 print:hidden ${
                            checkedSteps.includes(idx) ? 'bg-brand-fresa' : 'bg-brand-fresa/10'
                          }`}></div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
              
              <div className="mt-16 pt-12 border-t border-brand-fresa/5 flex flex-col items-center justify-center text-center print:hidden">
                <div className="w-20 h-20 bg-cream-soft rounded-full flex items-center justify-center mb-8 relative group">
                  <div className="absolute inset-0 bg-brand-fresa/10 rounded-full animate-ping opacity-20"></div>
                  <span className="text-3xl">👩‍🍳</span>
                </div>
                <p className="text-gray-600 font-serif italic text-xl mb-4">¡Buen provecho!</p>
                <div className="flex items-center space-x-4">
                  <span className="w-8 h-px bg-brand-fresa/20"></span>
                  <p className="text-sm text-brand-fresa font-bold uppercase tracking-[0.4em]">RecetaDolce Studio</p>
                  <span className="w-8 h-px bg-brand-fresa/20"></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Print Only Footer */}
        <div className="hidden print:block mt-12 pt-8 border-t border-gray-100">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-bold text-ink uppercase tracking-widest mb-1">Descubierto en RecetaDolce.com</p>
              <p className="text-sm text-gray-600">La excelencia culinaria española en tu hogar.</p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-600 uppercase tracking-widest">© <span suppressHydrationWarning>{new Date().getFullYear()}</span> RecetaDolce Studio</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

