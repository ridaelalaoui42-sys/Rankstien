import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

// Singleton instances
let supabaseInstance: ReturnType<typeof createClient> | null = null;
let supabaseAdminInstance: ReturnType<typeof createClient> | null = null;

export const getSupabase = () => {
  if (supabaseInstance) return supabaseInstance;
  
  if (!supabaseUrl || !supabaseAnonKey) {
    if (process.env.NODE_ENV === 'production') {
      console.error('CRITICAL: Supabase credentials missing in production! Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Vercel.');
    }
    return createChainProxy();
  }
  
  supabaseInstance = createClient(supabaseUrl, supabaseAnonKey);
  return supabaseInstance;
};

export const getSupabaseAdmin = () => {
  if (supabaseAdminInstance) return supabaseAdminInstance;

  if (!supabaseUrl || !supabaseServiceKey) {
    if (process.env.NODE_ENV === 'production') {
      console.error('CRITICAL: Supabase Admin credentials missing in production!');
    }
    return createChainProxy();
  }

  supabaseAdminInstance = createClient(supabaseUrl, supabaseServiceKey);
  return supabaseAdminInstance;
};

// A more robust chaining proxy that handles all common Supabase client methods
const createChainProxy = (): any => {
  const fn = () => ({ 
    data: null, 
    error: { message: 'Supabase credentials missing' }, 
    count: 0,
    single: () => Promise.resolve({ data: null, error: { message: 'Supabase credentials missing' } }),
    maybeSingle: () => Promise.resolve({ data: null, error: { message: 'Supabase credentials missing' } }),
    select: () => createChainProxy(),
    from: () => createChainProxy(),
    insert: () => createChainProxy(),
    update: () => createChainProxy(),
    delete: () => createChainProxy(),
    eq: () => createChainProxy(),
    order: () => createChainProxy(),
    limit: () => createChainProxy(),
  });
  
  const proxy = new Proxy(fn, {
    get: (target, prop) => {
      // If awaited, return a promise that resolves to the error state
      if (prop === 'then') {
        return (resolve: any) => resolve({ data: null, error: { message: 'Supabase credentials missing' }, count: 0 });
      }
      if (prop === 'single' || prop === 'maybeSingle') {
        return () => Promise.resolve({ data: null, error: { message: 'Supabase credentials missing' } });
      }
      return createChainProxy();
    },
    apply: (target, thisArg, argumentsList) => {
      return createChainProxy();
    }
  });

  return proxy;
};

export const supabase = getSupabase();
