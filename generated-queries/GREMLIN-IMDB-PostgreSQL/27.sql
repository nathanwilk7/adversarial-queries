SELECT count(*)
FROM aka_name, cast_info, kind_type, movie_companies, movie_info, movie_link, name, role_type, title
WHERE kind_type.kind = 'tv series'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
