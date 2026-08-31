SELECT count(*)
FROM cast_info, kind_type, link_type, movie_companies, movie_info, movie_keyword, movie_link, title
WHERE kind_type.kind = 'tv series'
  AND cast_info.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
