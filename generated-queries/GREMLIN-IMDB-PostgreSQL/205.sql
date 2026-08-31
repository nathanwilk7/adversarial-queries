SELECT count(*)
FROM keyword, kind_type, movie_info, movie_info_idx, movie_keyword, movie_link, title
WHERE kind_type.kind = 'tv series'
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
