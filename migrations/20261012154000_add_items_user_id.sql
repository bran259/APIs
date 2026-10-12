ALTER TABLE public.items
ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES auth.users (id);

CREATE INDEX IF NOT EXISTS items_user_id_idx
ON public.items (user_id);
