ALTER TABLE public.items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read their own items"
ON public.items
FOR SELECT
TO authenticated
USING ((select auth.uid()) = user_id);

CREATE POLICY "Users can create their own items"
ON public.items
FOR INSERT
TO authenticated
WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY "Users can update their own items"
ON public.items
FOR UPDATE
TO authenticated
USING ((select auth.uid()) = user_id)
WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY "Users can delete their own items"
ON public.items
FOR DELETE
TO authenticated
USING ((select auth.uid()) = user_id);
