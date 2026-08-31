SELECT count(*)
FROM cast_info, complete_cast, kind_type, movie_keyword, name, title
WHERE kind_type.kind = 'movie'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
